import os, discord
from discord.ext import commands
from discord import app_commands
import aiohttp, asyncio, secrets
import json

TOKEN = os.getenv("Discord_token")
GUILD_ID = str(os.getenv("Discord_guild_id"))
N8N_PLAN_URL = "  https://61698dbb9d52.ngrok-free.app/webhook/discord-bot"
QUIZ_URL = " https://61698dbb9d52.ngrok-free.app/webhook/quiz_agent"
SUBMIT_URL = " https://61698dbb9d52.ngrok-free.app/webhook/submit_answer"
# # 共用 n8n webhook 請求函式
# async def n8n_request(ctx, command):
#     if ctx.interaction:
#         await ctx.interaction.response.defer(ephemeral=True)
#     payload = {
#         "user_id": str(ctx.author.id),
#         "user_name": ctx.author.global_name or ctx.author.name,
#         "guild_id": str(ctx.guild.id) if ctx.guild else None,
#         "channel_id": str(ctx.channel.id),
#         "command": command
#     }
#     async with bot.http_sess.post(str(N8N_PLAN_URL), json=payload) as r:
#         if r.status != 200:
#             await ctx.send("n8n 無法回應")
#             return None
#         return await r.json()
# 設置 quiz post to n8n
# ── n8n 回傳題目資料的預期格式 ──
# {
#   "question_id": "Q42",
#   "type": "MCQ_SINGLE" | "MCQ_MULTI",
#   "question": "題目文字",
#   "choices": ["A 選項", "B 選項", "C 選項", "D 選項"],   # 已在 n8n 洗牌
#   "meta": {
#     "source": "章節/教材",
#     "level": "Understand|Apply",
#     "strategy": "出題策略標籤",
#     "hints": ["提示1","提示2","提示3"]                     # 可為空陣列
#   }
# }
# async def get_question(user_id: str, session_id: str, tag: str | None = None):
#     payload = {"intent":"get_question","user_id":user_id,"session_id":session_id,"strategy":{"tag":tag} if tag else {}}
#     async with aiohttp.ClientSession() as s:
#         async with s.post(QUIZ_URL, json=payload, timeout=10) as r:
#             r.raise_for_status()
#             return await r.json()

# async def submit_answer(user_id, session_id, qid, selected_letters):
#     url = SUBMIT_URL
#     payload = {
#         "user_id": user_id,
#         "session_id": session_id,
#         "question_id": qid,
#         "selected_letters": selected_letters
#     }
#     async with aiohttp.ClientSession() as s:
#         async with s.post(url, json=payload, timeout=20) as r:
#             text = await r.text()
#             if r.status >= 400:
#                 raise RuntimeError(f"n8n {r.status}: {text}")
#             try:
#                 data = json.loads(text)
#             except Exception:
#                 raise RuntimeError(f"期待 JSON，實得：{text}")
#             if isinstance(data, list) and data and isinstance(data[0], dict):
#                 data = data[0].get("json", data[0])
#             if not isinstance(data, dict):
#                 raise RuntimeError(f"期待物件，實得：{type(data).__name__} {data}")
#             return data

# # async def submit_answer(user_id: str, session_id: str, qid: str, picks: list[int]):
# #     payload = {"intent":"submit_only","user_id":user_id,"session_id":session_id,"question_id":qid,"selected_indexes":picks}
# #     async with aiohttp.ClientSession() as s:
# #         async with s.post(SUBMIT_URL, json=payload, timeout=10) as r:
# #             return r.status

intents = discord.Intents.default()
intents.message_content = True          #設置可得到訊息內容

# client = discord.Client(intents=intents)
bot = commands.Bot(command_prefix="!", intents=intents)       #暫時設置 "!"開頭的為命令，非官方的"/"
bot.http_sess = None


@bot.event
async def on_ready():
    if bot.http_sess is None:
        bot.http_sess = aiohttp.ClientSession()
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Logged in as {bot.user}")

#設置官方命令，需要先去同步官方伺服器，不用Hybrid_command，是因為此命令不開放給使用者使用
@bot.command()
@commands.has_permissions(administrator=True)   #只有管理員可以使用此命令
async def synccommands(ctx):
    await bot.tree.sync()
    await ctx.send("同步完成")




# 註冊成官方的"/"命令
@bot.hybrid_command()
async def ping(ctx):
    """測試機器人是否在線"""
    await ctx.send("pong")

# 功能:獲取計畫表
@bot.hybrid_command()
async def plan(ctx):
    """獲取計畫表"""
    data = await n8n_request(ctx, "plan")
    await ctx.send("正在獲取計畫表...")

# 功能:獲取目前已有教材
@bot.hybrid_command()
async def get_textbook(ctx):
    """獲取目前已有教材"""
    data = await n8n_request(ctx, "get_textbook")
    await ctx.send("正在獲取教材...")

# 功能:上傳檔案
@bot.hybrid_command()
async def upload(ctx):
    """上傳教材"""
    data = await n8n_request(ctx, "upload")
    await ctx.send("請將教材檔案直接拖移到此...")

# def normalize_q(q):
#     # 可能是列表或 {json:{...}}
#     if isinstance(q, list) and q:
#         q = q[0]
#     if isinstance(q, dict) and "json" in q and isinstance(q["json"], dict):
#         q = q["json"]

#     # 若沒有 meta，從 data table 原欄位合成
#     if isinstance(q, dict) and "meta" not in q:
#         r = q
#         hints = [r.get("hints1"), r.get("hints2"), r.get("hints3")]
#         hints = [h for h in hints if h]
#         multi = isinstance(r.get("answer_indexes"), list) and len(r["answer_indexes"]) > 1
#         q = {
#             "question_id": r.get("question_id") or r.get("id") or str(r.get("_id", "")),
#             "type": "MCQ_MULTI" if multi else "MCQ_SINGLE",
#             "question": r.get("question", ""),
#             "choices": [r.get("choice1"), r.get("choice2"), r.get("choice3"), r.get("choice4")],
#             "meta": {
#                 "source": r.get("source", ""),
#                 "level": r.get("level", ""),
#                 "strategy": r.get("Strategy") or r.get("strategy", ""),
#                 "hints": hints,
#             },
#         }
#         q["choices"] = [c for c in q["choices"] if c is not None]
#     return q

# # 答題設置
# def render_q(q: dict, hint_level: int = 0) -> str:
#     meta = q.get("meta") or {}
#     question = q.get("question", "<no question>")
#     choices = q.get("choices") or []

#     # 用 A/B/C/D… 標示；超過 26 個就退回數字
#     letters = [chr(65 + i) for i in range(min(len(choices), 26))]
#     def label(i: int) -> str:
#         return letters[i] if i < len(letters) else str(i + 1)

#     head = f"\n{question}"
#     opts = "\n".join(f"{label(i)}. {c}" for i, c in enumerate(choices))

#     tail = "\n\n（可多選）" if q.get("type") == "MCQ_MULTI" else ""
#     return head + ("\n" + opts if opts else "") + tail

# class MultiSelect(discord.ui.Select):
#     def __init__(self, n: int, multi: bool):
#         super().__init__(placeholder="選擇答案", min_values=1, max_values=(n if multi else 1),
#                          options=[discord.SelectOption(label=str(i+1)) for i in range(n)],
#                          custom_id="pick")

# class PlayView(discord.ui.View):
#     def __init__(self, user_id, session_id, q):
#         super().__init__(timeout=None)
#         self.user_id, self.session_id, self.q = user_id, session_id, q
#         self.hint_level = 0
#         self.selected = []
#         letters = ["A", "B", "C", "D"]
#         # 選項 Select (row=1)
#         options = [
#             discord.SelectOption(label=f"{chr(65+i)}. {c}", value=chr(65+i))
#             for i, c in enumerate(q["choices"])
#         ]
#         select = discord.ui.Select(
#             placeholder="選擇答案（可多選）",
#             min_values=1,
#             max_values=len(options),  # 無論單選多選都允許多選
#             options=options,
#             custom_id=f"pick:{self.session_id}:{q['question_id']}",
#             row=1,
#         )
#         select.callback = self.on_pick
#         self.add_item(select)

#         # 三顆按鈕 (row=0)
#         for label, style, name in [
#             ("送出", discord.ButtonStyle.success, "submit"),
#             ("取消", discord.ButtonStyle.danger, "cancel")
#         ]:
#             btn = discord.ui.Button(
#                 label=label, style=style,
#                 custom_id=f"{name}:{session_id}:{q['question_id']}",
#                 row=0
#             )
#             btn.callback = getattr(self, f"on_{name}")
#             self.add_item(btn)

#     async def on_pick(self, inter: discord.Interaction):
#         if str(inter.user.id) != self.user_id:
#             return await inter.response.send_message("不是你的題目。", ephemeral=True)
#         self.selected = inter.data.get("values") or []  # 直接存字母 ["A", "C"]陣列
#         await inter.response.defer()


# # 傳送作答給予n8n之後,submit_answer
#     async def on_submit(self, inter: discord.Interaction):
#         if str(inter.user.id) != self.user_id:
#             return await inter.response.send_message("不是你的題目。", ephemeral=True)
#         if not getattr(self, "selected", None):
#             return await inter.response.send_message("請先選擇答案。", ephemeral=True)

#         # 鎖定按鈕避免重複點擊
#         for c in self.children:
#             if isinstance(c, discord.ui.Button):
#                 c.disabled = True
#         await inter.response.defer()

#         # 呼叫 n8n
#         resp = await submit_answer(self.user_id, self.session_id, self.q["question_id"], self.selected)

#         # --- 資料格式安全解包 ---
#         import json
#         if isinstance(resp, str):
#             try:
#                 resp = json.loads(resp)
#             except Exception:
#                 return await inter.followup.send(f"AI 回傳非 JSON：{resp!r}", ephemeral=True)
#         if isinstance(resp, list) and resp and isinstance(resp[0], dict):
#             resp = resp[0].get("json", resp[0])
#         if isinstance(resp, dict) and "output" in resp:
#             resp = resp["output"]
#         if not isinstance(resp, dict):
#             return await inter.followup.send(f"回傳格式錯誤：{type(resp)} {resp}", ephemeral=True)
#         # ----------------------

#         print("=== submit payload ===", self.user_id, self.session_id, self.q["question_id"], self.selected)
#         print("=== n8n 回傳 ===", resp)

#         # --- 欄位解析與型別統一 ---
#         qid_resp = str(resp.get("question_id") or "")
#         qid_cur = str(self.q.get("question_id") or "")
#         result = resp.get("result", "")
#         analyze = resp.get("analyze", "")
#         action = resp.get("next_action", "retry")
#         next_hint = resp.get("next_hint", "")
#         try:
#             score = float(resp.get("score", 0) or 0)
#         except Exception:
#             score = 0.0
#         try:
#             self.hint_level = int(resp.get("hint_level", 0) or 0)
#         except Exception:
#             self.hint_level = 0
#         # --------------------------

#         if not qid_resp:
#             for c in self.children:
#                 if isinstance(c, discord.ui.Button):
#                     c.disabled = False
#             return await inter.followup.edit_message(
#                 message_id=inter.message.id,
#                 content=render_q(self.q, self.hint_level) + "\n\n❗回傳缺少 question_id",
#                 view=self
#             )

#         if qid_resp != qid_cur:
#             for c in self.children:
#                 if isinstance(c, discord.ui.Button):
#                     c.disabled = False
#             return await inter.followup.edit_message(
#                 message_id=inter.message.id,
#                 content=render_q(self.q, self.hint_level) +
#                         f"\n\n❗question_id 不一致：回傳={qid_resp} 目前={qid_cur}",
#                 view=self
#             )

#         # --- 根據決策更新 ---
#         if action == "next":
#             nxt = await get_question(self.user_id, self.session_id, tag=None)
#             self.q = nxt
#             self.hint_level = 0
#             new_view = PlayView(self.user_id, self.session_id, self.q)
#             return await inter.followup.edit_message(
#                 message_id=inter.message.id,
#                 content=render_q(self.q, 0) + f"\n\n結果：{result}。{analyze}",
#                 view=new_view
#             )

#         # 同題情況
#         body = render_q(self.q, self.hint_level)
#         suffix = f"\n\n結果：{result}。{analyze}"
#         if action == "hint" and next_hint:
#             suffix += f"\n提示：{next_hint}"

#         # 解鎖按鈕以便重試
#         for c in self.children:
#             if isinstance(c, discord.ui.Button):
#                 c.disabled = False

#         await inter.followup.edit_message(
#             message_id=inter.message.id,
#             content=body + suffix,
#             view=self
#         )


#     async def on_hint(self, inter: discord.Interaction):
#         if str(inter.user.id) != self.user_id:
#             return await inter.response.send_message("不是你的題目。", ephemeral=True)
#         await inter.response.defer()
#         hints = (self.q.get("meta") or {}).get("hints") or []
#         self.hint_level = min(self.hint_level + 1, len(hints))
#         await inter.followup.edit_message(
#             message_id=inter.message.id,
#             content=render_q(self.q, self.hint_level),
#             view=self
#         )

#     async def on_cancel(self, inter: discord.Interaction):
#         if str(inter.user.id) != self.user_id:
#             return await inter.response.send_message("不是你的題目。", ephemeral=True)
#         await inter.response.edit_message(content="已取消。", view=None)



#     async def interaction_check(self, inter: discord.Interaction) -> bool:
#         if str(inter.user.id) != self.user_id:
#             await inter.response.send_message("不是你的題目。", ephemeral=True); return False
#         return True

  
#     async def submit(self, inter: discord.Interaction, _btn: discord.ui.Button):
#         await inter.response.defer()
#         picks = [int(v) for v in self.selector.values]  # 1-based
#         _ = await submit_answer(self.user_id, self.session_id, self.q["question_id"], picks)
#         txt = render_q(self.q, self.hint_level) + "\n\n✅ 已送出答案，等待評分。"
#         await inter.followup.edit_message(message_id=inter.message.id, content=txt, view=self)

  
#     async def hint(self, inter: discord.Interaction, _btn: discord.ui.Button):
#         await inter.response.defer()
#         hints = self.q["meta"].get("hints", [])
#         if not hints:
#             return await inter.followup.edit_message(message_id=inter.message.id,
#                                                      content=render_q(self.q)+ "\n\n（此題無提示）", view=self)
#         self.hint_level = min(self.hint_level+1, len(hints))
#         await inter.followup.edit_message(message_id=inter.message.id,
#                                           content=render_q(self.q, self.hint_level), view=self)

#     async def cancel(self, inter: discord.Interaction, _btn: discord.ui.Button):
#         await inter.response.edit_message(content="已取消。", view=None)


# # 功能:開始答題
# @bot.hybrid_command(name="quiz")
# async def quiz(ctx: commands.Context, tag: str | None = None):
#     """開始答題"""
#     uid = str(ctx.author.id); sid = secrets.token_hex(8)
#     if ctx.interaction:  # slash 呼叫
#         await ctx.interaction.response.defer(ephemeral=True)
#         q = await get_question(uid, sid, tag)
#         q_raw = await get_question(uid, sid, tag)
#         # print("q_raw =", q_raw)
#         q = normalize_q(q_raw)
#         if not q.get("choices"):
#             await ctx.interaction.followup.send("此題沒有可用選項。", ephemeral=True); return
#         view = PlayView(uid, sid, q)             
#         await ctx.interaction.followup.send(render_q(q), view=view, ephemeral=True)
#         # print("q_raw:", q_raw)
#     else:  # 前綴呼叫
#         q = await get_question(uid, sid, tag)
#         await ctx.send(render_q(q), view=PlayView(uid, sid, q))
#         # print("q_raw:", q_raw)


# # 設置遊戲的dc ui
# class PlayView(discord.ui.View):
#     def __init__(self):
#         super().__init__(timeout=None)   #設置不會超時

#     @discord.ui.button(label="取消", style=discord.ButtonStyle.red, custom_id="cancel")
#     async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
#         await interaction.response.edit_message(content = "取消遊戲....", view=None)

# # 設置遊戲
# @bot.hybrid_command()
# async def play(ctx):
#     """開始遊戲"""
#     await ctx.send("開始猜拳", view=PlayView())

bot.run(TOKEN)
