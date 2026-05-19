"""
Night resolution engine.
Processes all night actions in the correct order and returns a list of event strings.
"""
import random
from typing import Optional
from game import Game, Player, Role, Phase, MAFIA_TEAM, ROLE_EMOJIS


def get_role_name(role: Role) -> str:
    from handlers import ROLE_NAMES_UZ
    return ROLE_NAMES_UZ.get(role, role.value)


def _record_visit(game: Game, visitor_id: int, target_id: int):
    if target_id not in game.night_visitors:
        game.night_visitors[target_id] = []
    game.night_visitors[target_id].append(visitor_id)


async def resolve_night(game: Game, context) -> list[str]:
    """
    Returns a list of narrative strings describing what happened.
    Also handles side-effect DMs (Sehrgar choice, Daydi/Jurnalist reports, Serzhant report).
    Mutates game state (eliminations, role changes).
    """
    events = []
    actions = game.night_actions
    alive = {p.user_id: p for p in game.alive_players()}

    # --- 1. Determine who is blocked (Kezuvchi) ---
    kezuvchi_action = actions.get(Role.KEZUVCHI)
    if kezuvchi_action and kezuvchi_action in alive:
        game.blocked.add(kezuvchi_action)
        _record_visit(game, _uid(game, Role.KEZUVCHI), kezuvchi_action)

    def is_blocked(uid: int) -> bool:
        return uid in game.blocked

    # --- 2. Record all night visitors ---
    for role in [Role.DOCTOR, Role.KOMISSAR, Role.SERZHANT, Role.DAYDI,
                 Role.JURNALIST, Role.ADVOKAT, Role.AFERIST, Role.JOKER,
                 Role.KIMYOGAR, Role.SOTQIN, Role.GAZABKOR]:
        actor = game.get_alive_by_role(role)
        if actor:
            target_id = actions.get(role)
            if target_id and target_id in alive:
                _record_visit(game, actor.user_id, target_id)

    # Mafia/Don visits target
    mafia_target = actions.get("mafia_kill")
    if mafia_target and mafia_target in alive:
        for p in game.alive_mafia_team():
            if p.role in (Role.DON, Role.MAFIA):
                _record_visit(game, p.user_id, mafia_target)

    yq = game.get_alive_by_role(Role.YOLLANMA_QOTIL)
    if yq and actions.get(Role.YOLLANMA_QOTIL):
        _record_visit(game, yq.user_id, actions[Role.YOLLANMA_QOTIL])

    qotil = game.get_alive_by_role(Role.QOTIL)
    if qotil and actions.get(Role.QOTIL):
        _record_visit(game, qotil.user_id, actions[Role.QOTIL])

    minior = game.get_alive_by_role(Role.MINIOR)
    if minior and actions.get(Role.MINIOR):
        game.mines_set.add(actions[Role.MINIOR])

    # --- 3. Advokat protection ---
    advokat_action = actions.get(Role.ADVOKAT)
    if advokat_action and not is_blocked(_uid(game, Role.ADVOKAT)):
        game.advokat_protected = advokat_action

    # --- 4. Aferist identity swap ---
    aferist_actor = game.get_alive_by_role(Role.AFERIST)
    aferist_target = actions.get(Role.AFERIST)
    if aferist_actor and aferist_target and not is_blocked(aferist_actor.user_id):
        target_p = alive.get(aferist_target)
        if target_p:
            fake_names = [p.display_name for p in alive.values() if p.user_id != aferist_target]
            if fake_names:
                game.aferist_swaps[aferist_target] = random.choice(fake_names)

    # --- 5. Kimyogar ---
    kimyogar = game.get_alive_by_role(Role.KIMYOGAR)
    kimyogar_target = actions.get(Role.KIMYOGAR)
    kimyogar_mode = actions.get("kimyogar_mode", "heal")
    kimyogar_kill_target = None
    kimyogar_save_target = None
    if kimyogar and kimyogar_target and not is_blocked(kimyogar.user_id):
        if kimyogar_mode == "kill":
            kimyogar_kill_target = kimyogar_target
        else:
            kimyogar_save_target = kimyogar_target

    # --- 6. Collect kills ---
    pending_kills: dict[int, str] = {}  # target_id -> cause

    mafia_kill = actions.get("mafia_kill")
    if mafia_kill and mafia_kill in alive:
        acting_mafia = [p for p in game.alive_mafia_team() if p.role in (Role.DON, Role.MAFIA)]
        if acting_mafia and not any(is_blocked(p.user_id) for p in acting_mafia):
            pending_kills[mafia_kill] = "mafia"

    yq_target = actions.get(Role.YOLLANMA_QOTIL)
    if yq and yq_target and yq_target in alive and not is_blocked(yq.user_id):
        komissar = game.get_alive_by_role(Role.KOMISSAR) or game.get_alive_by_role(Role.SERZHANT)
        if komissar and yq_target == komissar.user_id:
            pending_kills[yq.user_id] = "komissar_counter"
        else:
            pending_kills[yq_target] = "yollanma"

    qotil_target = actions.get(Role.QOTIL)
    if qotil and qotil_target and qotil_target in alive and not is_blocked(qotil.user_id):
        pending_kills[qotil_target] = "qotil"

    if kimyogar_kill_target and kimyogar_kill_target in alive:
        pending_kills[kimyogar_kill_target] = "kimyogar"

    # --- 7. Komissar / Serzhant investigation ---
    komissar = game.get_alive_by_role(Role.KOMISSAR)
    serzhant = game.get_alive_by_role(Role.SERZHANT)
    active_komissar = komissar if komissar else (serzhant if serzhant and not komissar else None)
    komissar_target = None
    komissar_result_text = ""
    if active_komissar and not is_blocked(active_komissar.user_id):
        k_target_id = actions.get(Role.KOMISSAR) or actions.get(Role.SERZHANT)
        if k_target_id and k_target_id in alive:
            komissar_target = alive[k_target_id]
            is_actually_mafia = komissar_target.role in MAFIA_TEAM
            is_advokat_shielded = k_target_id == game.advokat_protected
            apparent_mafia = is_actually_mafia and not is_advokat_shielded

            komissar_result_text = (
                f"🔴 *{komissar_target.display_name}* — *MAFIYA!*"
                if apparent_mafia
                else f"🟢 *{komissar_target.display_name}* — Mafiya emas."
            )
            if apparent_mafia:
                pending_kills[k_target_id] = "komissar"
            elif is_actually_mafia and is_advokat_shielded:
                komissar_result_text += " (Advokat himoyasida — fuqaro ko'rindi)"

    # --- 8. Doctor / Kimyogar saves ---
    doctor = game.get_alive_by_role(Role.DOCTOR)
    doctor_save = None
    if doctor and not is_blocked(doctor.user_id):
        doctor_save = actions.get(Role.DOCTOR)

    saves = set()
    if doctor_save:
        saves.add(doctor_save)
    if kimyogar_save_target:
        saves.add(kimyogar_save_target)

    # --- 9. Sehrgar immunity ---
    sehrgar = game.get_alive_by_role(Role.SEHRGAR)
    sehrgar_attackers = []
    if sehrgar:
        for target_id, cause in list(pending_kills.items()):
            if target_id == sehrgar.user_id and cause in ("mafia", "komissar", "qotil"):
                sehrgar_attackers.append((cause, pending_kills.pop(target_id, None)))
        if sehrgar_attackers:
            try:
                keyboard_rows = []
                for cause, _ in sehrgar_attackers:
                    attacker_label = {"mafia": "Mafiya", "komissar": "Komissar", "qotil": "Qotil"}.get(cause, cause)
                    game.sehrgar_pending[cause] = True
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                choices = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🕊️ Rahm qilish (kechirish)", callback_data=f"sehrgar:spare:{game.chat_id}")],
                    [InlineKeyboardButton("⚡ O'ldirish", callback_data=f"sehrgar:kill:{game.chat_id}")],
                ])
                attacker_names = ", ".join({"mafia": "Mafiya", "komissar": "Komissar", "qotil": "Qotil"}.get(c, c) for c, _ in sehrgar_attackers)
                await context.bot.send_message(
                    sehrgar.user_id,
                    f"🧙‍ *{attacker_names} sizni o'ldirmoqchi bo'ldi — lekin kuchsiz!*\n\n"
                    "Nima qilasiz?",
                    reply_markup=choices,
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    # --- 10. Omadli survival chance ---
    omadli = game.get_alive_by_role(Role.OMADLI)
    if omadli and omadli.user_id in pending_kills:
        if random.random() < 0.5:
            pending_kills.pop(omadli.user_id)
            events.append(f"🍀 *{omadli.display_name}* (Omadli) — o'lim daqiqasida omon qoldi!")

    # --- 11. Remove saved targets ---
    for saved_id in saves:
        if saved_id in pending_kills:
            pending_kills.pop(saved_id)
            saved_p = alive.get(saved_id)
            if saved_p:
                events.append(f"💊 *{saved_p.display_name}* bu kecha himoya qilindi va omon qoldi!")

    # --- 12. Afsungar counter-kill ---
    afsungar = game.get_alive_by_role(Role.AFSUNGAR)
    afsungar_counter_kills = set()
    if afsungar and afsungar.user_id in pending_kills:
        cause = pending_kills[afsungar.user_id]
        if cause in ("mafia", "yollanma", "qotil", "kimyogar"):
            for p in game.alive_players():
                if p.role in (Role.DON, Role.MAFIA) and cause == "mafia":
                    afsungar_counter_kills.add(p.user_id)
                elif p.role == Role.YOLLANMA_QOTIL and cause == "yollanma":
                    afsungar_counter_kills.add(p.user_id)
                elif p.role == Role.QOTIL and cause == "qotil":
                    afsungar_counter_kills.add(p.user_id)
                elif p.role == Role.KIMYOGAR and cause == "kimyogar":
                    afsungar_counter_kills.add(p.user_id)

    # --- 13. Bo'ri transformation ---
    bori = game.get_alive_by_role(Role.BO_RI)
    bori_transform = None
    if bori and bori.user_id in pending_kills:
        cause = pending_kills[bori.user_id]
        if cause == "mafia" or cause == "yollanma":
            bori_transform = "mafia"
            pending_kills.pop(bori.user_id)
        elif cause == "komissar":
            bori_transform = "serzhant"
            pending_kills.pop(bori.user_id)
        elif cause == "qotil":
            pass

    # --- 14. Apply eliminations ---
    eliminated_players = []
    for target_id in list(pending_kills.keys()):
        target_p = alive.get(target_id)
        if target_p:
            game.eliminate_player(target_id)
            eliminated_players.append((target_p, pending_kills[target_id]))

    # Afsungar counter-kills
    for uid in afsungar_counter_kills:
        p = alive.get(uid)
        if p and p.alive:
            game.eliminate_player(uid)
            events.append(f"💥 *Afsungar* o'limi bilan *{p.display_name}*ni ham o'ldirdi!")

    # --- 15. Mine explosions ---
    for mined_id in game.mines_set:
        visitors = game.night_visitors.get(mined_id, [])
        for visitor_id in visitors:
            visitor_p = game.players.get(visitor_id)
            if visitor_p and visitor_p.alive and (minior is None or visitor_id != minior.user_id):
                game.eliminate_player(visitor_id)
                events.append(f"💥 *{visitor_p.display_name}* — mina portlashida halok bo'ldi!")

    # --- 16. Bo'ri transformation apply ---
    if bori_transform and bori:
        if bori_transform == "mafia":
            bori.role = Role.MAFIA
            bori.alive = True
            events.append(f"🐺 *{bori.display_name}* Mafiya tomonidan o'ldirildi va keyingi tundan boshlab *Mafiyaga aylandi!*")
            try:
                await context.bot.send_message(
                    bori.user_id,
                    "🐺 Siz Mafiya tomonidan o'ldirildi — lekin *Mafiaga aylandingiz!*\n\n"
                    "Keyingi tundan boshlab Mafiya bilan birga ishlaysiz.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        elif bori_transform == "serzhant":
            if not game.get_alive_by_role(Role.SERZHANT):
                bori.role = Role.SERZHANT
                bori.alive = True
                events.append(f"🐺 *{bori.display_name}* Komissar tomonidan o'ldirildi va *Serjantga aylandi!*")
                try:
                    await context.bot.send_message(
                        bori.user_id,
                        "🐺 Komissar sizni o'ldirdi — lekin *Serjantga aylandingiz!*\n\n"
                        "Endi fuqarolar tomonida o'ynaysiz.",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass
            else:
                bori.alive = False
                events.append(f"☠️ *{bori.display_name}* (Bo'ri) — Komissar tomonidan o'ldirildi.")

    # --- 17. Serzhant promotion if Komissar dead ---
    if komissar and not komissar.alive and serzhant and serzhant.alive:
        serzhant.role = Role.KOMISSAR
        events.append(f"🕵🏼 *{serzhant.display_name}* — Komissar o'ldirildi, Serjant yangi *Komissar Katani* bo'ldi!")
        try:
            await context.bot.send_message(
                serzhant.user_id,
                "🕵🏼 *Komissar o'ldirildi!*\n\nSiz endi *Komissar Katani*siz.\nFuqarolarni himoya qiling!",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    # --- 18. Admiral promotion if Komissar + Serzhant both dead ---
    admiral = game.get_alive_by_role(Role.ADMIRAL)
    if admiral:
        new_komissar = game.get_alive_by_role(Role.KOMISSAR)
        new_serzhant = game.get_alive_by_role(Role.SERZHANT)
        if not new_komissar and not new_serzhant:
            admiral.role = Role.KOMISSAR
            events.append(f"🧑🏻‍✈️ *{admiral.display_name}* — Komissar va Serjant yo'q, Admiral *Komissar Kataniga* aylandi!")
            try:
                await context.bot.send_message(
                    admiral.user_id,
                    "🧑🏻‍✈️ *Komissar va Serjant ikkovlari o'ldi!*\n\nSiz endi *Komissar Katani*siz.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    # --- 19. Build elimination narrative ---
    for player, cause in eliminated_players:
        role_name = get_role_name(player.role)
        emoji = ROLE_EMOJIS.get(player.role, "")
        events.append(f"☠️ *{player.display_name}* yo'q qilindi. Roli: {emoji} *{role_name}*")

    if not eliminated_players and not events:
        events.append("🛡️ Bu kecha hech kim yo'q qilinmadi!")

    # --- 20. Send Komissar result to Serzhant ---
    if komissar_result_text and komissar and komissar.alive:
        try:
            await context.bot.send_message(
                komissar.user_id,
                f"🔍 *Tekshiruv natijasi:*\n{komissar_result_text}",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    new_serzhant_p = game.get_alive_by_role(Role.SERZHANT)
    if komissar_result_text and new_serzhant_p and new_serzhant_p.role == Role.SERZHANT:
        try:
            await context.bot.send_message(
                new_serzhant_p.user_id,
                f"👮🏼 *Komissar tekshiruv natijasi (sizga xabar):*\n{komissar_result_text}",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    # --- 21. Daydi report ---
    daydi = game.get_alive_by_role(Role.DAYDI)
    daydi_target_id = actions.get(Role.DAYDI)
    if daydi and daydi_target_id and not is_blocked(daydi.user_id):
        visitors = game.night_visitors.get(daydi_target_id, [])
        visitor_names = [game.players[v].display_name for v in visitors if v in game.players and v != daydi.user_id]
        target_p = game.players.get(daydi_target_id)
        if target_p:
            if visitor_names:
                vis_text = ", ".join(visitor_names)
                msg = f"🧙‍♂️ *{target_p.display_name}* uyiga bu kecha kelganlar: {vis_text}"
            else:
                msg = f"🧙‍♂️ *{target_p.display_name}* uyiga bu kecha hech kim kelmadi."
            try:
                await context.bot.send_message(daydi.user_id, msg, parse_mode="Markdown")
            except Exception:
                pass

    # --- 22. Jurnalist report to mafia ---
    jurnalist = game.get_alive_by_role(Role.JURNALIST)
    jurnalist_target_id = actions.get(Role.JURNALIST)
    if jurnalist and jurnalist_target_id and not is_blocked(jurnalist.user_id):
        visitors = game.night_visitors.get(jurnalist_target_id, [])
        visitor_names = [game.players[v].display_name for v in visitors if v in game.players and v != jurnalist.user_id]
        target_p = game.players.get(jurnalist_target_id)
        if target_p:
            if visitor_names:
                vis_text = ", ".join(visitor_names)
                msg = f"👩🏼‍💻 *Intervyu natijasi ({target_p.display_name} uyi):*\nBu kecha kelganlar: {vis_text}"
            else:
                msg = f"👩🏼‍💻 *{target_p.display_name}* uyiga bu kecha hech kim kelmadi."
            for mafia_p in game.alive_mafia_team():
                try:
                    await context.bot.send_message(mafia_p.user_id, msg, parse_mode="Markdown")
                except Exception:
                    pass

    # --- 23. Sotqin expose (if their target is mafia) ---
    sotqin = game.get_alive_by_role(Role.SOTQIN)
    sotqin_target = actions.get(Role.SOTQIN)
    if sotqin and sotqin_target and not is_blocked(sotqin.user_id):
        t = game.players.get(sotqin_target)
        if t and t.role in (Role.DON, Role.MAFIA, Role.QOTIL):
            role_name = get_role_name(t.role)
            emoji = ROLE_EMOJIS.get(t.role, "")
            events.append(f"🤓 *Maxfiy manba:* *{t.display_name}* — {emoji} *{role_name}* ekan!")

    # --- 24. Joker card result ---
    joker = game.get_alive_by_role(Role.JOKER)
    joker_target = actions.get(Role.JOKER)
    if joker and joker_target and joker_target in alive and not is_blocked(joker.user_id):
        if random.random() < 0.25:
            t = alive[joker_target]
            if t.alive:
                game.eliminate_player(joker_target)
                role_name = get_role_name(t.role)
                emoji = ROLE_EMOJIS.get(t.role, "")
                events.append(f"🤡 *{t.display_name}* Joker kartasidan *o'lim kartasini tanladi* va halok bo'ldi! Roli: {emoji} {role_name}")
                joker.joker_won = True

    # --- 25. G'azabkor target tracking ---
    gazabkor = game.get_alive_by_role(Role.GAZABKOR)
    gazabkor_target = actions.get(Role.GAZABKOR)
    if gazabkor and gazabkor_target and not is_blocked(gazabkor.user_id):
        if gazabkor_target == gazabkor.user_id:
            killed_by_gazabkor = []
            for uid in gazabkor.gazabkor_targets:
                p = game.players.get(uid)
                if p and p.alive:
                    game.eliminate_player(uid)
                    killed_by_gazabkor.append(p.display_name)
            game.eliminate_player(gazabkor.user_id)
            if len(gazabkor.gazabkor_targets) >= 3:
                events.append(f"🧟 *G'azabkor* o'zini qurbon qildi! *{', '.join(killed_by_gazabkor)}* va G'azabkorning o'zi halok bo'ldi. *G'azabkor g'alaba qozondi!*")
            else:
                events.append(f"🧟 *G'azabkor* o'zini qurbon qildi! *{', '.join(killed_by_gazabkor) or 'hech kim'}* va G'azabkorning o'zi halok bo'ldi.")
        else:
            t = game.players.get(gazabkor_target)
            if t and gazabkor_target not in gazabkor.gazabkor_targets:
                gazabkor.gazabkor_targets.append(gazabkor_target)
                try:
                    await context.bot.send_message(
                        gazabkor.user_id,
                        f"🧟 *{t.display_name}* ro'yxatingizga qo'shildi. Jami: {len(gazabkor.gazabkor_targets)} kishi.\n"
                        f"Kamida 3 kishi to'plang, so'ng o'zingizni tanlang!",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

    return events


def _uid(game: Game, role: Role) -> Optional[int]:
    p = game.get_alive_by_role(role)
    return p.user_id if p else None
