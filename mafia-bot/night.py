"""
Night resolution engine for aiogram version.
"""
import random
from typing import Optional
from aiogram import Bot
from game import Game, Player, Role, MAFIA_TEAM, CITIZEN_TEAM, ROLE_EMOJIS
from profiles import get_profile, save_profile
from settings import get_settings


def _use_item(uid: int, field: str) -> bool:
    """Consume one unit of a shop item. Returns True if item was available."""
    p = get_profile(uid)
    count = getattr(p, field, 0)
    if count > 0:
        setattr(p, field, count - 1)
        save_profile(p)
        return True
    return False


def _role_name(role: Role) -> str:
    from handlers import ROLE_NAMES_UZ
    return ROLE_NAMES_UZ.get(role, role.value)


def _record_visit(game: Game, visitor_id: int, target_id: int):
    game.night_visitors.setdefault(target_id, []).append(visitor_id)


async def _dm(bot: Bot, uid: int, text: str, keyboard=None):
    try:
        await bot.send_message(uid, text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception:
        pass


async def resolve_night(game: Game, bot: Bot) -> list[str]:
    events = []
    actions = game.night_actions
    alive = {p.user_id: p for p in game.alive_players()}
    protection_enabled = get_settings(game.chat_id).protection_enabled

    # 1. Kezuvchi blocks (drug_protect item counters it)
    kez_target = actions.get(Role.KEZUVCHI)
    if kez_target and kez_target in alive:
        if protection_enabled and _use_item(kez_target, "drug_protect"):
            events.append(f"💊 *{alive[kez_target].display_name}* doridan himoya qilindi — blok o'tmadi!")
            await _dm(bot, kez_target, "💊 *Dori himoyangiz* ishga tushdi! Kezuvchi sizi uxlata olmadi.")
        else:
            game.blocked.add(kez_target)
            _record_visit(game, _uid(game, Role.KEZUVCHI), kez_target)

    def blocked(uid): return uid in game.blocked

    # 2. Record visitors
    for role in [Role.DOCTOR, Role.KOMISSAR, Role.SERZHANT, Role.DAYDI, Role.JURNALIST,
                 Role.ADVOKAT, Role.AFERIST, Role.JOKER, Role.KIMYOGAR, Role.SOTQIN, Role.GAZABKOR]:
        actor = game.get_alive_by_role(role)
        if actor:
            t = actions.get(role)
            if t and t in alive:
                _record_visit(game, actor.user_id, t)

    mafia_target = actions.get("mafia_kill")
    if mafia_target and mafia_target in alive:
        for p in game.alive_mafia_team():
            if p.role in (Role.DON, Role.MAFIA):
                _record_visit(game, p.user_id, mafia_target)

    yq = game.get_alive_by_role(Role.YOLLANMA_QOTIL)
    yq_t = actions.get(Role.YOLLANMA_QOTIL)
    if yq and yq_t:
        _record_visit(game, yq.user_id, yq_t)

    qotil = game.get_alive_by_role(Role.QOTIL)
    qotil_t = actions.get(Role.QOTIL)
    if qotil and qotil_t:
        _record_visit(game, qotil.user_id, qotil_t)

    minior = game.get_alive_by_role(Role.MINIOR)
    minior_t = actions.get(Role.MINIOR)
    if minior and minior_t:
        game.mines_set.add(minior_t)

    # 3. Advokat protection
    adv_t = actions.get(Role.ADVOKAT)
    adv_actor = game.get_alive_by_role(Role.ADVOKAT)
    if adv_actor and adv_t and not blocked(adv_actor.user_id):
        game.advokat_protected = adv_t

    # 4. Aferist swap (slip_protect counters it)
    afer = game.get_alive_by_role(Role.AFERIST)
    afer_t = actions.get(Role.AFERIST)
    if afer and afer_t and not blocked(afer.user_id) and afer_t in alive:
        if protection_enabled and _use_item(afer_t, "slip_protect"):
            await _dm(bot, afer_t, "🪤 *Sirpanishdan himoyangiz* ishga tushdi! Aferist sizning shaxsingizni almashtira olmadi.")
        else:
            others = [p.display_name for p in alive.values() if p.user_id != afer_t]
            if others:
                game.aferist_swaps[afer_t] = random.choice(others)

    # 5. Kimyogar
    kim = game.get_alive_by_role(Role.KIMYOGAR)
    kim_t = actions.get(Role.KIMYOGAR)
    kim_mode = actions.get("kimyogar_mode", "heal")
    kim_kill = kim_save = None
    if kim and kim_t and not blocked(kim.user_id):
        if kim_mode == "kill":
            kim_kill = kim_t
        else:
            kim_save = kim_t

    # 6. Collect kills
    pending: dict[int, str] = {}

    if mafia_target and mafia_target in alive:
        acting = [p for p in game.alive_mafia_team() if p.role in (Role.DON, Role.MAFIA)]
        if acting and not any(blocked(p.user_id) for p in acting):
            pending[mafia_target] = "mafia"

    if yq and yq_t and yq_t in alive and not blocked(yq.user_id):
        k_active = game.get_alive_by_role(Role.KOMISSAR) or game.get_alive_by_role(Role.SERZHANT)
        if k_active and yq_t == k_active.user_id:
            pending[yq.user_id] = "komissar_counter"
        else:
            pending[yq_t] = "yollanma"

    if qotil and qotil_t and qotil_t in alive and not blocked(qotil.user_id):
        pending[qotil_t] = "qotil"

    if kim_kill and kim_kill in alive:
        pending[kim_kill] = "kimyogar"

    konchi = game.get_alive_by_role(Role.KONCHI)
    if konchi and actions.get("konchi_mine"):
        pending[konchi.user_id] = "konchi_mine"

    # 6b. Labarant — protects Mafia team targets, poisons everyone else.
    labarant = game.get_alive_by_role(Role.LABARANT)
    lab_t = actions.get(Role.LABARANT)
    if labarant and lab_t and lab_t in alive and not blocked(labarant.user_id):
        lab_target = alive[lab_t]
        if lab_target.role in MAFIA_TEAM:
            if lab_t in pending:
                pending.pop(lab_t)
            events.append("🧪 Labarant davolovchi eliksirni ishga soldi.")
            await _dm(bot, labarant.user_id, f"🧪 *{lab_target.display_name}*ni himoya qildingiz.")
        else:
            pending[lab_t] = "labarant"
            events.append("☠️ Labarant o'lim eliksirini ishga soldi.")
            await _dm(bot, labarant.user_id, f"🧪 *{lab_target.display_name}*ni zaharladingiz.")

    # Mafia's bullet can't touch the Labarant
    if labarant and pending.get(labarant.user_id) == "mafia":
        pending.pop(labarant.user_id)

    # 6c. Qaroqchi — steals money or deals HP damage (independent role)
    qaroqchi = game.get_alive_by_role(Role.QAROQCHI)
    if qaroqchi and not blocked(qaroqchi.user_id):
        for action_key in ["qaroqchi_action1", "qaroqchi_action2"]:
            action = actions.get(action_key)
            if not action:
                continue
            mode, tid = action
            target = alive.get(tid)
            if not target:
                continue
            if mode == "steal":
                amount = random.randint(50, 100)
                tp = get_profile(tid)
                if tp.dollar >= amount:
                    tp.dollar -= amount
                    save_profile(tp)
                    qp = get_profile(qaroqchi.user_id)
                    if not qp.infinite_dollar:
                        qp.dollar += amount
                    save_profile(qp)
                    await _dm(bot, qaroqchi.user_id,
                        f"💰 *{target.display_name}*dan *{amount}$* o'g'irladingiz!")
                    await _dm(bot, tid,
                        f"💸 Kimdir kechasi *{amount}$* o'g'irladi! Hisobingiz kamaydi.")
                else:
                    # Not enough money — deal 50 HP damage instead
                    target.hp = max(0, target.hp - 50)
                    await _dm(bot, qaroqchi.user_id,
                        f"💸 *{target.display_name}*da yetarli pul yo'q — uning joni 50% kamaydi.")
                    await _dm(bot, tid,
                        f"🗡️ Kimdir kechasi sizga hujum qildi — joniningiz 50% kamaydi! (Qolgan: {target.hp}%)")
                    if target.hp <= 0 and tid not in pending:
                        pending[tid] = "qaroqchi_hp"
            elif mode == "attack":
                target.hp = max(0, target.hp - 50)
                await _dm(bot, qaroqchi.user_id,
                    f"⚔️ *{target.display_name}*ga hujum qildingiz! Joni {target.hp}% qoldi.")
                await _dm(bot, tid,
                    f"🗡️ Kechasi birov sizga hujum qildi — joniningiz 50% kamaydi! (Qolgan: {target.hp}%)")
                if target.hp <= 0 and tid not in pending:
                    pending[tid] = "qaroqchi_hp"

    # 6d. Enforce HP invariant: any alive player at 0 HP must die (regardless of pending state)
    for p in list(alive.values()):
        if p.hp <= 0 and p.user_id not in pending:
            pending[p.user_id] = "qaroqchi_hp"

    # 7. Komissar investigation
    komissar = game.get_alive_by_role(Role.KOMISSAR)
    serzhant = game.get_alive_by_role(Role.SERZHANT)
    active_k = komissar or serzhant
    komissar_result = ""
    komissar_found_mafia_name = None
    komissar_mode = actions.get("komissar_mode", "check")
    if active_k and not blocked(active_k.user_id):
        k_t = actions.get(Role.KOMISSAR) or actions.get(Role.SERZHANT)
        if k_t and k_t in alive:
            target_p = alive[k_t]
            if komissar_mode == "kill":
                pending[k_t] = "komissar_kill"
                komissar_result = f"🔫 *{target_p.display_name}* otib tashlandi!"
            else:
                is_mafia = target_p.role in MAFIA_TEAM
                shielded = k_t == game.advokat_protected
                doc_shield = is_mafia and protection_enabled and _use_item(k_t, "documents")
                if doc_shield:
                    await _dm(bot, k_t, "📁 *Hujjat himoyangiz* ishga tushdi! Komissar sizi tekshirdi, lekin siz fuqaro ko'rindingiz.")
                apparent = is_mafia and not shielded and not doc_shield
                komissar_result = (
                    f"🔴 *{target_p.display_name}* — *MAFIYA!*"
                    if apparent else
                    f"🟢 *{target_p.display_name}* — Mafiya emas."
                )
                if apparent:
                    komissar_found_mafia_name = target_p.display_name
                game.komissar_investigations.setdefault(active_k.user_id, []).append(
                    (target_p.display_name, _role_name(target_p.role))
                )

    # 8. Doctor / kimyogar saves
    doc = game.get_alive_by_role(Role.DOCTOR)
    saves = set()
    if doc and not blocked(doc.user_id):
        ds = actions.get(Role.DOCTOR)
        if ds:
            saves.add(ds)
    if kim_save:
        saves.add(kim_save)

    # 9. Sehrgar immunity
    sehrgar = game.get_alive_by_role(Role.SEHRGAR)
    if sehrgar and sehrgar.user_id in pending:
        cause = pending[sehrgar.user_id]
        if cause in ("mafia", "komissar", "komissar_kill", "qotil"):
            pending.pop(sehrgar.user_id)
            game.sehrgar_pending[cause] = True
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🕊️ Rahm qilish", callback_data=f"sehrgar:spare:{game.chat_id}")],
                [InlineKeyboardButton(text="⚡ O'ldirish", callback_data=f"sehrgar:kill:{game.chat_id}")],
            ])
            cause_label = {"mafia": "Mafiya", "komissar": "Komissar", "komissar_kill": "Komissar", "qotil": "Qotil"}.get(cause, cause)
            await _dm(bot, sehrgar.user_id,
                f"🧙‍ *{cause_label} sizni o'ldirmoqchi bo'ldi — lekin kuchsiz!*\n\nNima qilasiz?", kb)

    # 10. Omadli
    omadli = game.get_alive_by_role(Role.OMADLI)
    if omadli and omadli.user_id in pending and random.random() < 0.5:
        pending.pop(omadli.user_id)
        events.append(f"🍀 *{omadli.display_name}* (Omadli) — o'lim daqiqasida omon qoldi!")

    # 11. Remove saved + shop shield / killer_protect items
    for sid in saves:
        if sid in pending:
            pending.pop(sid)
            sp = alive.get(sid)
            if sp:
                events.append(f"💊 *{sp.display_name}* himoya qilindi va omon qoldi!")

    for tid, cause in list(pending.items()):
        tp = alive.get(tid)
        if not tp:
            continue
        if cause == "qotil" and protection_enabled and _use_item(tid, "killer_protect"):
            pending.pop(tid)
            events.append(f"⛑️ *{tp.display_name}* — Qotildan himoya ishga tushdi! Omon qoldi.")
            await _dm(bot, tid, "⛑️ *Qotildan himoyangiz* ishga tushdi! Qotil seni o'ldira olmadi.")
        elif protection_enabled and _use_item(tid, "shield"):
            pending.pop(tid)
            events.append(f"🛡 *{tp.display_name}* — Himoya qalqoni ishga tushdi! Omon qoldi.")
            await _dm(bot, tid, "🛡 *Himoya qalqoningiz* ishga tushdi! Bu kecha omon qoldingiz.")

    # 12. Afsungar counter-kill
    afsungar = game.get_alive_by_role(Role.AFSUNGAR)
    afs_counters = set()
    if afsungar and afsungar.user_id in pending:
        cause = pending[afsungar.user_id]
        role_map = {
            "mafia": {Role.DON, Role.MAFIA},
            "yollanma": {Role.YOLLANMA_QOTIL},
            "qotil": {Role.QOTIL},
            "kimyogar": {Role.KIMYOGAR},
            "komissar_kill": {Role.KOMISSAR, Role.SERZHANT},
        }
        for p in game.alive_players():
            if p.role in role_map.get(cause, set()):
                afs_counters.add(p.user_id)

    # 13a. Tulki transformation
    tulki = game.get_alive_by_role(Role.TULKI)
    tulki_t = actions.get(Role.TULKI)
    tulki_new_role = None
    if tulki and tulki_t and tulki_t in alive and tulki_t != tulki.user_id and not blocked(tulki.user_id):
        target = alive[tulki_t]
        if target.role in MAFIA_TEAM:
            tulki_new_role = Role.MAFIA
        elif target.role in CITIZEN_TEAM:
            tulki_new_role = Role.SERZHANT
        else:
            tulki_new_role = Role.QOTIL

    # 13. Bo'ri transformation
    bori = game.get_alive_by_role(Role.BO_RI)
    bori_transform = None
    if bori and bori.user_id in pending:
        cause = pending[bori.user_id]
        if cause in ("mafia", "yollanma"):
            bori_transform = "mafia"
            pending.pop(bori.user_id)
        elif cause in ("komissar", "komissar_kill"):
            bori_transform = "serzhant"
            pending.pop(bori.user_id)

    # 14. Apply kills
    eliminated = []
    for tid, cause in pending.items():
        tp = alive.get(tid)
        if tp:
            game.eliminate_player(tid)
            eliminated.append((tp, cause))

    for uid in afs_counters:
        p = alive.get(uid)
        if p and p.alive:
            game.eliminate_player(uid)
            events.append(f"💥 *Afsungar* o'limi bilan *{p.display_name}*ni ham o'ldirdi!")

    # 15. Mine explosions
    for mined_id in game.mines_set:
        for vid in game.night_visitors.get(mined_id, []):
            vp = game.players.get(vid)
            if vp and vp.alive and (not minior or vid != minior.user_id):
                game.eliminate_player(vid)
                events.append(f"💥 *{vp.display_name}* — mina portlashida halok bo'ldi!")

    # 16. Bo'ri transform
    if bori_transform and bori:
        if bori_transform == "mafia":
            bori.role = Role.MAFIA
            bori.alive = True
            events.append(f"🐺 *{bori.display_name}* Mafiaga aylandi!")
            await _dm(bot, bori.user_id,
                "🐺 Mafiya tomonidan o'ldirildi — lekin siz *Mafiaga aylandingiz!*\n"
                "Keyingi tundan boshlab Mafiya bilan ishlaysiz.")
        elif bori_transform == "serzhant":
            if not game.get_alive_by_role(Role.SERZHANT):
                bori.role = Role.SERZHANT
                bori.alive = True
                events.append(f"🐺 *{bori.display_name}* Serjantga aylandi!")
                await _dm(bot, bori.user_id, "🐺 *Serjantga aylandingiz!* Fuqarolar tomonida o'ynaysiz.")
            else:
                bori.alive = False

    # 16a. Tulki transform
    if tulki_new_role and tulki and tulki.alive:
        tulki.role = tulki_new_role
        if tulki_new_role == Role.MAFIA:
            events.append(f"🦊 *{tulki.display_name}* Mafiaga aylandi!")
            await _dm(bot, tulki.user_id,
                "🦊 Tanlagan nishoningiz Mafiya ekan — siz *Mafiaga aylandingiz!*\n"
                "Keyingi tundan boshlab Mafiya bilan ishlaysiz.")
        elif tulki_new_role == Role.SERZHANT:
            events.append(f"🦊 *{tulki.display_name}* Serjantga aylandi!")
            await _dm(bot, tulki.user_id,
                "🦊 Tanlagan nishoningiz tinch aholi ekan — siz *Serjantga aylandingiz!*")
        else:
            events.append(f"🦊 *{tulki.display_name}* Qotilga aylandi!")
            await _dm(bot, tulki.user_id,
                "🦊 Tanlagan nishoningiz mustaqil o'yinchi ekan — siz *Qotilga aylandingiz!*\n"
                "Endi shahardagi hammani yo'q qilishingiz kerak!")

    # 17. Serzhant promotion
    if komissar and not komissar.alive and serzhant and serzhant.alive:
        serzhant.role = Role.KOMISSAR
        events.append(f"🕵🏼 *{serzhant.display_name}* — yangi Komissar Katani!")
        await _dm(bot, serzhant.user_id, "🕵🏼 *Komissar o'ldirildi!* Siz endi *Komissar Katani*siz.")

    # 18. Admiral promotion
    admiral = game.get_alive_by_role(Role.ADMIRAL)
    if admiral and not game.get_alive_by_role(Role.KOMISSAR) and not game.get_alive_by_role(Role.SERZHANT):
        admiral.role = Role.KOMISSAR
        events.append(f"🧑🏻‍✈️ *{admiral.display_name}* — Admiral Komissar Kataniga aylandi!")
        await _dm(bot, admiral.user_id, "🧑🏻‍✈️ *Komissar va Serjant o'ldi!* Siz endi *Komissar Katani*siz.")

    # 19. Elimination narrative
    for p, cause in eliminated:
        rn = _role_name(p.role)
        em = ROLE_EMOJIS.get(p.role, "")
        events.append(f"☠️ *{p.display_name}* yo'q qilindi. Roli: {em} *{rn}*")

    if not eliminated and not events:
        events.append("🛡️ Bu kecha hech kim yo'q qilinmadi!")

    # 20. Komissar result DM
    if komissar_result:
        if active_k and active_k.alive:
            await _dm(bot, active_k.user_id, f"🔍 *Tekshiruv natijasi:*\n{komissar_result}")
        new_s = game.get_alive_by_role(Role.SERZHANT)
        if new_s and new_s.role == Role.SERZHANT and new_s.user_id != active_k.user_id:
            await _dm(bot, new_s.user_id, f"👮🏼 *Komissar tekshiruv natijasi:*\n{komissar_result}")

    # 21. Daydi report
    daydi = game.get_alive_by_role(Role.DAYDI)
    daydi_t = actions.get(Role.DAYDI)
    if daydi and daydi_t and not blocked(daydi.user_id):
        visitors = [game.players[v].display_name for v in game.night_visitors.get(daydi_t, [])
                    if v in game.players and v != daydi.user_id]
        tp = game.players.get(daydi_t)
        if tp:
            msg = (f"🧙‍♂️ *{tp.display_name}* uyiga bu kecha kelganlar: {', '.join(visitors)}"
                   if visitors else f"🧙‍♂️ *{tp.display_name}* uyiga bu kecha hech kim kelmadi.")
            await _dm(bot, daydi.user_id, msg)

    # 22. Jurnalist report
    jurn = game.get_alive_by_role(Role.JURNALIST)
    jurn_t = actions.get(Role.JURNALIST)
    if jurn and jurn_t and not blocked(jurn.user_id):
        visitors = [game.players[v].display_name for v in game.night_visitors.get(jurn_t, [])
                    if v in game.players and v != jurn.user_id]
        tp = game.players.get(jurn_t)
        if tp:
            msg = (f"👩🏼‍💻 *Intervyu ({tp.display_name} uyi):* kelganlar: {', '.join(visitors)}"
                   if visitors else f"👩🏼‍💻 *{tp.display_name}* uyiga bu kecha hech kim kelmadi.")
            for mp in game.alive_mafia_team():
                await _dm(bot, mp.user_id, msg)

    # 23. Sotqin expose
    sotqin = game.get_alive_by_role(Role.SOTQIN)
    sotqin_t = actions.get(Role.SOTQIN)
    if sotqin and sotqin_t and sotqin_t != 0 and not blocked(sotqin.user_id):
        sp = game.players.get(sotqin_t)
        if sp and sp.role in (Role.DON, Role.MAFIA, Role.QOTIL):
            rn = _role_name(sp.role)
            em = ROLE_EMOJIS.get(sp.role, "")
            events.append(f"🤓 *Maxfiy manba:* *{sp.display_name}* — {em} *{rn}* ekan!")

    # 24. Joker
    joker = game.get_alive_by_role(Role.JOKER)
    joker_t = actions.get(Role.JOKER)
    if joker and joker_t and joker_t in alive and not blocked(joker.user_id):
        if random.random() < 0.25:
            tp = alive[joker_t]
            if tp.alive:
                game.eliminate_player(joker_t)
                rn = _role_name(tp.role)
                em = ROLE_EMOJIS.get(tp.role, "")
                events.append(f"🤡 *{tp.display_name}* Joker kartasidan o'lim kartasini tanladi! Roli: {em} {rn}")
                joker.joker_won = True

    # 25. G'azabkor
    gazabkor = game.get_alive_by_role(Role.GAZABKOR)
    gazabkor_t = actions.get(Role.GAZABKOR)
    if gazabkor and gazabkor_t and not blocked(gazabkor.user_id):
        if gazabkor_t == gazabkor.user_id:
            killed = []
            for uid in gazabkor.gazabkor_targets:
                gp = game.players.get(uid)
                if gp and gp.alive:
                    game.eliminate_player(uid)
                    killed.append(gp.display_name)
            game.eliminate_player(gazabkor.user_id)
            suffix = "— *G'azabkor g'alaba qozondi!*" if len(gazabkor.gazabkor_targets) >= 3 else ""
            events.append(f"🧟 *G'azabkor* o'zini qurbon qildi! Bilan: {', '.join(killed) or 'hech kim'} {suffix}")
        else:
            tp = game.players.get(gazabkor_t)
            if tp and gazabkor_t not in gazabkor.gazabkor_targets:
                gazabkor.gazabkor_targets.append(gazabkor_t)
                await _dm(bot, gazabkor.user_id,
                    f"🧟 *{tp.display_name}* ro'yxatga qo'shildi. Jami: *{len(gazabkor.gazabkor_targets)}* kishi.\n"
                    f"Kamida 3 ta to'plab, o'zingizni tanlang!")

    # 26. Konchi morning announcement
    if konchi:
        events.append(game.konchi_morning_msg or "⛏️ Konchi tunda hech narsa topmadi.")

    game.komissar_found_mafia = komissar_found_mafia_name
    return events


def _uid(game: Game, role: Role) -> Optional[int]:
    p = game.get_alive_by_role(role)
    return p.user_id if p else None
