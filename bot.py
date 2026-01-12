import discord
from discord.ext import commands
from discord import ui
import httpx
import json
import logging
import re
import asyncio
from discord import ButtonStyle
import datetime
from dotenv import load_dotenv
import os
# ==========================================
# ⚙️ 配置區 [請務必修改這裡]
# ==========================================
# 追蹤每個 Thread 的狀態 (例如: "learning", "reviewing")
thread_status = {}

# 載入 .env 檔案中的變數
load_dotenv()

# 從環境變數取得所有 URL/Token（已由 .env 提供，故移除程式內建預設網址）
BOT_TOKEN = os.getenv("BOT_TOKEN")

N8N_EXAM_WEBHOOK_URL = os.getenv("N8N_EXAM_WEBHOOK_URL")
N8N_PLANNER_WEBHOOK_URL = os.getenv("N8N_PLANNER_WEBHOOK_URL")
N8N_STATS_API_URL = os.getenv("N8N_STATS_API_URL")

N8N_GET_TASKS_URL = os.getenv("N8N_GET_TASKS_URL")
N8N_UPDATE_TASK_URL = os.getenv("N8N_UPDATE_TASK_URL")

N8N_CHECK_USER_URL = os.getenv("N8N_CHECK_USER_URL")
N8N_REGISTER_URL = os.getenv("N8N_REGISTER_URL")

N8N_Upload_URL = os.getenv("N8N_Upload_URL")

N8N_LEARNING_WEBHOOK_URL = os.getenv("N8N_LEARNING_WEBHOOK_URL")

GET_RESULT_URL = os.getenv("GET_RESULT_URL")
N8N_READ_URL = os.getenv("N8N_READ_URL")

# ==========================================
# 🤖 Bot 初始化與設定
# ==========================================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------------------------------------------------
# 核心橋接函式 (Core Bridge Function)
# ------------------------------------------------------------------

async def handle_n8n_backend(message_or_interaction, target_url: str, action: str = None, extra_data: dict = None):
    """將 Discord 訊息/互動打包，發送到 n8n 核心邏輯，並處理回應與 UI 狀態變更。"""
    
    # 1. 統一取得 channel 與 user 物件 (兼容 Message 與 Interaction)
    if isinstance(message_or_interaction, discord.Interaction):
        context_obj = message_or_interaction
        channel = message_or_interaction.channel
        user = message_or_interaction.user
        content = ""
    else:
        context_obj = message_or_interaction
        channel = message_or_interaction.channel
        user = message_or_interaction.author
        content = message_or_interaction.content

    # 顯示輸入中
    if isinstance(context_obj, discord.Interaction):
        if not context_obj.response.is_done():
            await context_obj.response.defer()
    else:
        await channel.trigger_typing()

    # 準備 Payload
    task_index_from_arg = extra_data.get("task_index") if extra_data else None
    
    payload = {
        "thread_id": str(channel.id),
        "user_id": str(user.id),
        "user_name": user.name,
        "user_message": content,
        "action": action,
        "thread_name": channel.name
    }
    if extra_data: payload.update(extra_data)
    # print(f"🚀 [DEBUG] Sending to N8N: {payload}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(target_url, json=payload, timeout=120.0)
            response.raise_for_status() 
            
            data = response.json()
            
            # =======================================================
            # 🛡️ [變數安全初始化]
            # =======================================================
            raw_text = None
            feedback = None
            score = None
            is_passed = None
            actions = []
            reply_text = "（AI 處理完成，但未回傳文字）"
            
            # =======================================================
            # 🔄 [核心修正] 智能讀取資料 (支援 Dict 與 JSON String)
            # =======================================================
            
            # 1. 抓取原始欄位
            raw_content = (
                data.get("output") or 
                data.get("reply") or 
                data.get("feedback") or
                data.get("quiz_question")
            )

            # 2. 判斷型態並提取資料
            if isinstance(raw_content, dict):
                # 情況 A: N8N 直接回傳了 JSON 物件 (Dict)
                inner_data = raw_content
                if "score" in inner_data: score = inner_data["score"]
                if "is_passed" in inner_data: is_passed = inner_data["is_passed"]
                if "feedback" in inner_data: feedback = inner_data["feedback"]
                raw_text = feedback if feedback else str(inner_data)

            elif isinstance(raw_content, str):
                # 情況 B: N8N 回傳了字串，嘗試解析是否為 JSON
                cleaned_text = raw_content.strip()
                if cleaned_text.startswith("```"): # 去除 Markdown
                    cleaned_text = re.sub(r"^```(json)?|```$", "", cleaned_text, flags=re.MULTILINE).strip()
                
                if cleaned_text.startswith("{") and cleaned_text.endswith("}"):
                    try:
                        inner_data = json.loads(cleaned_text)
                        if "score" in inner_data: score = inner_data["score"]
                        if "is_passed" in inner_data: is_passed = inner_data["is_passed"]
                        if "feedback" in inner_data: feedback = inner_data["feedback"]
                        raw_text = feedback if feedback else cleaned_text
                    except json.JSONDecodeError:
                        raw_text = cleaned_text # 解析失敗就當普通文字
                else:
                    raw_text = cleaned_text 

            # 3. 補充：如果外層 data 就有 score/actions，優先權高於內層
            if data.get("score") is not None: score = data.get("score")
            if data.get("is_passed") is not None: is_passed = data.get("is_passed")
            if data.get("actions"): actions = data.get("actions")

            # 4. 決定最終顯示文字
            if feedback:
                reply_text = feedback
            elif raw_text and isinstance(raw_text, str):
                reply_text = raw_text

            # =======================================================
            # 🚩 邏輯判斷：根據分數決定 UI
            # =======================================================
            if action == "submit_answer":
                if score is not None: score = int(score)

                # 如果 N8N 沒給 actions，我們自己推斷
                if not actions: 
                    if is_passed is True or (score is not None and score >= 60):
                        actions.append("show_complete_button")
                    else:
                        actions.append("review_challenge")

            # 取得 task_index
            current_task_index = str(data.get("task_index") or task_index_from_arg or "0")
            thread_id = str(channel.id)

            # =======================================================
            # 🎨 UI 美化與狀態更新
            # =======================================================
            if action == "submit_answer" and score is not None:
                status_emoji = "🎉" if score >= 90 else ("✅" if score >= 60 else "💪")
                status_title = "表現優異" if score >= 90 else ("通過挑戰" if score >= 60 else "未達標準")
                
                reply_text = f"### {status_emoji} 評測結果：{score} 分 ({status_title})\n\n{reply_text}"

                if score < 60:
                    thread_status[thread_id] = None 
                else:
                    thread_status[thread_id] = "completed"

            # =======================================================
            # 🛠️ 決定 View (按鈕介面)
            # =======================================================
            view_to_send = None
            
            if "show_complete_button" in actions:
                # 🔥 這裡傳入 target_url，解決衝突的關鍵
                view_to_send = TaskCompleteView(target_url=target_url, task_index=current_task_index)
                if action == "submit_answer": 
                    reply_text += "\n\n✨ **恭喜！您已證明實力，請點擊下方按鈕結案。**"

            elif "review_challenge" in actions:
                view_to_send = ChallengeView(task_index=current_task_index)

            elif action in ["request_hint", "student_stuck"]:
                view_to_send = None 

            elif action is None and thread_status.get(thread_id) != "completed":
                pass 

            # =======================================================
            # 📤 發送訊息
            # =======================================================
            if isinstance(context_obj, discord.Interaction):
                await context_obj.followup.send(reply_text, view=view_to_send)
            else:
                await channel.send(reply_text, view=view_to_send)
                
            if data.get("force_close"):
                await asyncio.sleep(5)
                if isinstance(channel, discord.Thread):
                    await channel.delete()

    except Exception as e:
        err_msg = f"❌ 系統處理錯誤：{str(e)}"
        if isinstance(context_obj, discord.Interaction):
            await context_obj.followup.send(err_msg, ephemeral=True)
        else:
            await channel.send(err_msg)
        print(f"[Error] handle_n8n_backend: {e}")

# ------------------------------------------------------------------
# 各種 UI View (處理結束或繼續的按鈕):

# ==========================================
# 註冊相關 View (Modal)
# ==========================================
# 1.註冊用的視窗 
class RegisterModal(ui.Modal):
    def __init__(self):
        super().__init__(title="🎉 歡迎來到 SRL 學習助教")

        self.add_item(ui.InputText(
            label="您的電子信箱 (用於接收行事曆)",
            placeholder="example@gmail.com",
            style=discord.InputTextStyle.short
        ))
        
        self.add_item(ui.InputText(
            label="您的稱呼",
            placeholder="例如：吳同學",
            style=discord.InputTextStyle.short
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        email = self.children[0].value
        name = self.children[1].value
        user_id = str(interaction.user.id)
        # 不管是在 #general 還是某個 Thread，直接抓當下的 ID
        current_channel_id = str(interaction.channel.id)
        # 呼叫 n8n 註冊 API
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    N8N_REGISTER_URL, 
                    json={
                        "user_id": user_id, 
                        "email": email, 
                        "user_name": name,
                        "dm_channel_id": current_channel_id
                    },
                    timeout=70.0
                )
            
            await interaction.followup.send(f"✅ 註冊成功！你好 {name}，現在您可以開始學習 了。", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ 註冊失敗，請聯繫管理員。({e})", ephemeral=True)

# 2.註冊按鈕 View (當發現用戶未註冊時顯示)
class RegisterView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="📝 立即註冊", style=discord.ButtonStyle.primary)
    async def register_btn(self, button, interaction):
        await interaction.response.send_modal(RegisterModal())

# 3.通用的檢查函式 (在每個指令前呼叫)
# 您需要在 n8n 建立一個簡單的 GET API 來檢查 user_id 是否存在
async def check_user_registered(user_id):
    try:
        async with httpx.AsyncClient() as client:
            # N8N_CHECK_USER_URL 是一個簡單的 API，回傳 {"registered": true/false}
            resp = await client.get(N8N_CHECK_USER_URL, params={"user_id": user_id})
            if resp.status_code == 200:
                return resp.json().get("registered", False)
    except:
        return False # 網路錯誤當作沒註冊，避免報錯
    return False

# ==========================================
# 學生室相關 View (Modal)
# ==========================================
# 1.任務完成按鈕 View (顯示在私密 Thread 中)
class TaskCompleteView(ui.View):
    def __init__(self, target_url, task_index):
        super().__init__(timeout=None)
        self.target_url = target_url  # 🔥 接收並儲存目標 URL (分辨是考試還是學習)
        self.task_index = task_index

    @ui.button(label="✅ 完成此任務", style=discord.ButtonStyle.success, custom_id="btn_task_done")
    async def done_button(self, button: ui.Button, interaction: discord.Interaction):
        
        await interaction.response.defer()
        button.disabled = True
        button.label = "處理中..."
        await interaction.message.edit(view=self)

        # 🔥 使用傳進來的 target_url，自動回報給正確的 Agent
        await handle_n8n_backend(
            interaction,
            self.target_url,
            action="complete_task",
            extra_data={"task_index": self.task_index}
        )

# 2.任務選擇選單 View (顯示在主頻道回應中)
class TaskSelectView(ui.View):
    def __init__(self, task_options):
        super().__init__(timeout=70)
        # 保存原始的完整資料列表
        self.task_options = task_options 
        
        select = ui.Select(
            placeholder="請選擇您現在要執行的任務...",
            options=[
                discord.SelectOption(
                    # 這裡只管選單顯示，就算被截斷也沒關係
                    description=opt.get('description', '')[:100], # 加個切片防止過長報錯
                    value=str(opt['value']),
                    label=opt['label']          
                ) for opt in task_options
            ]
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_value = self.children[0].values[0]
        
        # 從 self.task_options (原始清單) 中尋找完整物件
        selected_task_data = next(
            (item for item in self.task_options if str(item['value']) == selected_value), 
            None
        )

        # 這裡抓取到的 full_content 是沒有被 100 字限制摧毀的原始資料
        full_content = selected_task_data.get('full_content') or selected_task_data.get('label')

        # 🔥 [新增] 嘗試抓取 plan_id (如果 N8N 沒傳，就預設 "unknown")
        plan_id = selected_task_data.get('plan_id', 'unknown_plan')

        try:
            # 1. 建立 Thread
            thread_title = (full_content[:20] + "...") if len(full_content) > 20 else full_content
            thread_name = f"🚀 [學習中] {thread_title}"
            
            thread = await interaction.channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread
            )
            await thread.add_user(interaction.user)

            # =================================================
            # 🚀 UX 優化：先發送「AI 準備中」的佔位訊息 (取得遙控器 loading_msg)
            # =================================================
            loading_msg = await thread.send("🔄 **AI 教練正在閱讀教材並準備學習環境...**")

            # 2. 發送同步訊號給 n8n
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    N8N_LEARNING_WEBHOOK_URL, 
                    json={
                        "action": "init_context",      # 標記這是「初始化」
                        "user_id": str(interaction.user.id),
                        "thread_id": str(thread.id),
                        "task_content": full_content  # 完整內容
                    },
                    timeout=20.0
                )
                
                # 3. 解析 n8n 回傳並「原地變身」
                if response.status_code == 200:
                    data = response.json()
                    init_reply = data.get("reply") # 取得 n8n 裡的初始化開場白
                    
                    if init_reply:
                        # ✅ 成功：把「準備中」改成「AI 的正式開場白」
                        await loading_msg.edit(content=init_reply)
                    else:
                        # 沒回傳文字：刪除 loading 訊息，避免留在那邊尷尬
                        await loading_msg.delete()
                else:
                    # ❌ 失敗：顯示錯誤訊息
                    await loading_msg.edit(content=f"⚠️ 初始化連線錯誤 (Status: {response.status_code})，但您仍可繼續嘗試對話。")

            # 4. 發送任務詳情 Embed (這部分保持不變，接在 AI 說話之後)
            embed = discord.Embed(
                title="📖 任務詳細內容",
                description=f"**內容：**\n{full_content}\n\n卡關時請直接提問，我會協助您。",
                color=0x00FF00
            )
            # 傳入 topic 與 webhook url
            await thread.send(
                embed=embed, 
                view=StudyRoomView(
                    task_index=selected_value,
                    task_topic=full_content,       # 傳入任務內容當作主題
                    n8n_url=N8N_LEARNING_WEBHOOK_URL, # 確保 View 知道要打哪個 API                   
                )
            )

            # 5. 更新原本的 Slash Command 回應
            await interaction.followup.send(f"✅ 已進入學習間：<#{thread.id}>", ephemeral=True)
            
        except Exception as e:
            print(f"Error in select_callback: {e}")
            await interaction.followup.send(f"❌ 發生錯誤: {e}", ephemeral=True)

# 3.1 追蹤每個討論串點擊「接受挑戰」的次數
attempt_tracker = {}

# 3.2 [修改] 學習室的主控台 (原本的 ChallengeView 升級版)
class StudyRoomView(discord.ui.View):
    def __init__(self, task_index: str, task_topic: str, n8n_url: str):
        super().__init__(timeout=None)
        self.task_index = task_index
        self.task_topic = task_topic
        self.n8n_url = n8n_url
    
    # 按鈕 1: 寫筆記 (新增的)
    @discord.ui.button(label="📝 寫筆記", style=discord.ButtonStyle.primary, custom_id="btn_write_note", row=0)
    async def write_note_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 開啟 SmartNoteModal
        await interaction.response.send_modal(
            SmartNoteModal(
                n8n_url=self.n8n_url,
                user_id=interaction.user.id,
                user_name=interaction.user.name,
                task_topic=self.task_topic,
                task_index=self.task_index,
                thread_id=interaction.channel.id
            )
        )

    # 按鈕 2: 結案挑戰 (原本的)
    @discord.ui.button(label="🎯 接受挑戰 (結案)", style=discord.ButtonStyle.success, custom_id="challenge_btn", row=0)
    async def review_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 移除按鈕，避免重複點擊
        await interaction.response.edit_message(view=None)
        
        thread_id = str(interaction.channel.id)
        
        # 1. 紀錄狀態
        thread_status[thread_id] = "request_review"
        attempt_tracker[thread_id] = attempt_tracker.get(thread_id, 0) + 1
        
        # 2. 呼叫後端
        await handle_n8n_backend(
            interaction.message, 
            self.n8n_url,  # 使用傳入的 URL
            action="request_review",
            extra_data={
                "task_index": self.task_index,
                "attempt_count": attempt_tracker[thread_id],
                "user_id": str(interaction.user.id)
            }
        )

# 4.定義詳細紀錄查看的 View( task_result 的 ui)
class ResultDetailView(discord.ui.View):
    def __init__(self, learning_process, full_history):
        super().__init__(timeout=None)
        self.learning_process = learning_process
        self.full_history = full_history

    @discord.ui.button(label="📜 學習過程詳情", style=discord.ButtonStyle.secondary, custom_id="btn_learn_log")
    async def view_learning(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 處理 Learning_process (陣列格式)
        content = "## 📝 學習對話過程\n"
        if not self.learning_process:
            content += "無紀錄"
        else:
            for item in self.learning_process:
                # 假設格式為 {"role": "user", "content": "..."}
                role = "👤 學生" if "user" in str(item.get("role", "")).lower() else "🤖 教練"
                text = item.get("content") or item.get("text") or str(item)
                content += f"**{role}**: {text}\n"
        
        # 避免超過 Discord 2000 字限制
        await interaction.response.send_message(content[:1990], ephemeral=True)

    @discord.ui.button(label="⚔️ 挑戰過程詳情", style=discord.ButtonStyle.secondary, custom_id="btn_challenge_log")
    async def view_challenge(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 處理 full_history (陣列格式)
        content = "## ⚔️ 結案挑戰過程\n"
        if not self.full_history:
            content += "無紀錄"
        else:
            for item in self.full_history:
                text = item.get("content") or str(item)
                content += f"• {text}\n"

        await interaction.response.send_message(content[:1990], ephemeral=True)

# 5. 筆記輸入視窗
class SmartNoteModal(ui.Modal):
    def __init__(self, n8n_url, user_id, user_name, task_topic="一般學習", task_index="0", thread_id="0"):
        super().__init__(title="📝 讀書速記 (Brain Dump)")
        self.n8n_url = n8n_url
        self.user_id = user_id
        self.user_name = user_name
        self.task_topic = task_topic 
        self.task_index = task_index
        self.thread_id = thread_id 

        # 欄位 1: 定位標籤 (Context) - 讓學生簡單標記位置，選填即可
        self.add_item(ui.InputText(
            label="章節 / 頁數 / 關鍵字 (選填)",
            placeholder="例如：P.15、向量公式、或是留空...",
            style=discord.InputTextStyle.short,
            required=False # 👈 關鍵：設為非必填，降低阻力
        ))

        # 欄位 2: 速記內容 (Raw Content) - 大框框，隨便寫
        self.add_item(ui.InputText(
            label="筆記內容 (想法、疑問、重點...)",
            placeholder="隨意記錄您的想法，AI 會幫您整理和檢查...",
            style=discord.InputTextStyle.long, # 👈 使用長框 (Paragraph)
            required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # 取得輸入值
        user_tag = self.children[0].value  # 標籤
        raw_note = self.children[1].value  # 主要內容

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.n8n_url,
                    json={
                        "action": "process_note", # 動作代號不變
                        "user_id": str(self.user_id),
                        "user_name": self.user_name,
                        "task_index": str(self.task_index),
                        "thread_id": str(self.thread_id),
                        "task_topic": self.task_topic, # 這是大主題 (例如：三角函數)
                        "user_tag": user_tag,          # 這是學生自填的小標籤 (例如：P.15)
                        "note_content": raw_note,      # 這是最核心的速記內容
                        "timestamp": datetime.datetime.now().isoformat()
                    },
                    timeout=40.0 # 因 AI 要整理內容，稍微給多一點時間
                )

            if response.status_code == 200:
                data = response.json()
                # 這裡顯示 AI 整理後的結果或回饋
                ai_feedback = data.get("ai_feedback", "筆記已整理並歸檔！")
                
                await interaction.followup.send(
                    f"✅ **速記已儲存！**\n\n🤖 **AI 整理回饋：**\n{ai_feedback}", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"⚠️ 存檔失敗: {response.text}", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 連線錯誤: {e}", ephemeral=True)

# 5-1 筆記閱讀器
# --- 核心：分頁閱讀器 (Idea 2) ---
class NotePaginationView(ui.View):
    def __init__(self, title, content, doc_url):
        super().__init__(timeout=300) # 5分鐘後按鈕失效
        self.title = title
        self.content = content
        self.doc_url = doc_url
        
        # 設定每一頁顯示多少字 (Discord Embed 限制 4096，建議設 800-1000 比較舒適)
        self.chunk_size = 800 
        
        # 切割內容
        self.chunks = [content[i:i+self.chunk_size] for i in range(0, len(content), self.chunk_size)]
        if not self.chunks: self.chunks = ["(內容為空)"]
        
        self.current_page = 0

        # 初始化按鈕狀態
        self.update_buttons()
        
        # 🔥 Idea 1: 新增一個按鈕，讓學生可以去新視窗(瀏覽器)看
        self.add_item(discord.ui.Button(label="🔗 網頁版/原檔", url=self.doc_url, row=1))

    def update_buttons(self):
        # 第一頁時，鎖住「上一頁」
        self.children[0].disabled = (self.current_page == 0)
        # 最後一頁時，鎖住「下一頁」
        self.children[2].disabled = (self.current_page == len(self.chunks) - 1)
        # 更新頁數標籤
        self.children[1].label = f"第 {self.current_page + 1} / {len(self.chunks)} 頁"

    def get_embed(self):
        # 製作當前頁面的 Embed
        embed = discord.Embed(
            title=f"📖 {self.title}",
            description=self.chunks[self.current_page],
            color=discord.Color.green()
        )
        embed.set_footer(text="💡 使用下方按鈕翻頁，或點擊連結開啟完整版")
        return embed

    # [上一頁] 按鈕
    @ui.button(emoji="⬅️", style=discord.ButtonStyle.primary, row=0)
    async def prev_button(self, button, interaction):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # [頁數顯示] 按鈕 (純顯示用，點了沒反應)
    @ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True, row=0)
    async def page_counter(self, button, interaction):
        pass

    # [下一頁] 按鈕
    @ui.button(emoji="➡️", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, button, interaction):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    # 🔥 新增 [搜尋] 按鈕
    @ui.button(label="🔍 搜尋", style=discord.ButtonStyle.secondary, row=1)
    async def search_button(self, button, interaction):
        # 呼叫搜尋視窗，並把 "self" (目前的閱讀器) 傳給它
        await interaction.response.send_modal(SearchModal(self))
    
    # [關閉] 按鈕
    @ui.button(label="❌ 關閉", style=discord.ButtonStyle.danger, row=1)
    async def close_button(self, button, interaction):
        # 刪除這則訊息 (Self-destruct)
        # await interaction.message.delete()
        # 或者使用 edit 把內容清空：
        await interaction.response.edit_message(content="📕 筆記已關閉", embed=None, view=None)


# --- 1. 筆記選擇選單 ---
class NoteSelect(ui.Select):
    def __init__(self, notes_data): # 👈 修正：這裡只需要 notes_data，不需要 user_name 了
        options = []
        for note in notes_data:
            # N8N 已經給了漂亮的 label，直接用！
            label = note.get('label', '未命名筆記')
            file_id = note.get('value')
            description = note.get('original_name', '')

            options.append(discord.SelectOption(
                label=label[:100], 
                value=file_id, 
                description=description[:100], # 下方小字顯示原檔名
                emoji="📄"
            ))
        super().__init__(placeholder="請選擇要閱讀的筆記...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        file_id = self.values[0]
        selected_option = [x for x in self.options if x.value == file_id][0]
        
        try:
            # 呼叫 N8N 拿內容
            async with httpx.AsyncClient() as client:
                resp = await client.get(N8N_READ_URL, params={"action": "get_content", "file_id": file_id}, timeout=30.0)
                
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("content", "無內容")
                doc_url = f"https://docs.google.com/document/d/{file_id}"
                
                # 🔥 啟動分頁閱讀器
                view = NotePaginationView(title=selected_option.label, content=content, doc_url=doc_url)
                await interaction.followup.send(embed=view.get_embed(), view=view, ephemeral=True)
            else:
                await interaction.followup.send("❌ 讀取失敗", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 錯誤: {e}", ephemeral=True)

class NoteListView(ui.View):
    def __init__(self, notes_data):
        super().__init__()
        self.add_item(NoteSelect(notes_data))

# --- 搜尋關鍵字的彈出視窗 ---
class SearchModal(ui.Modal):
    def __init__(self, parent_view):
        super().__init__(title="🔍 搜尋筆記內容")
        self.parent_view = parent_view # 把閱讀器本身傳進來，這樣才能控制翻頁
        
        self.add_item(ui.InputText(
            label="請輸入關鍵字",
            placeholder="例如：傅立葉變換",
            min_length=1
        ))

    async def callback(self, interaction: discord.Interaction):
        keyword = self.children[0].value
        found = False

        # 遍歷所有頁面 (Chunks) 尋找關鍵字
        for index, chunk in enumerate(self.parent_view.chunks):
            if keyword in chunk:
                # ✅ 找到了！
                self.parent_view.current_page = index # 更新頁數
                self.parent_view.update_buttons()     # 更新按鈕狀態
                
                # ✨ 進階技巧：把關鍵字變色 (使用 Markdown 的 Python 語法高亮)
                # 注意：這會改變原始內容顯示，如果不喜歡可以只翻頁就好
                # highlighted_chunk = chunk.replace(keyword, f"``【{keyword}】``") 
                
                embed = self.parent_view.get_embed()
                # 提示使用者找到了
                embed.set_footer(text=f"🔍 已跳轉至包含「{keyword}」的頁面 (第 {index+1} 頁)")
                
                await interaction.response.edit_message(embed=embed, view=self.parent_view)
                found = True
                break # 找到第一個就停
        
        if not found:
            await interaction.response.send_message(f"❌ 找不到「{keyword}」，請嘗試其他關鍵字。", ephemeral=True)

# ==========================================
# 學生提交答案的彈出視窗 (Modal)
# ==========================================
# EXAM_MODEL - view: 學生回答問題的彈出視窗
class AnswerInputModal(ui.Modal):
    def __init__(self, task_index, question_text=""): # 新增 question_text 參數
        super().__init__(title="📝 提交解題過程")
        self.task_index = task_index
        
        # 把 LaTeX 轉成易讀的 Unicode 文字
        question_text = self.format_latex_to_unicode(question_text)
        # --- 🔥 [新增] 題目參考區 (偷吃步) ---
        # 雖然這是一個輸入框，但我們預填了題目，讓學生可以邊看邊寫
        self.add_item(ui.InputText(
            label="👀 題目參考 (請往下滑動填寫答案)",
            style=discord.InputTextStyle.long, # 長框，支援多行
            value=question_text[:3900], # 預填題目 (Discord 限制 4000 字，稍微截斷以防萬一)
            required=False # 設為非必填，學生不用改它
        ))
        
        # 欄位 2: 解題思路
        self.add_item(ui.InputText(
            label="我的解題思路 / 關鍵步驟",
            style=discord.InputTextStyle.long,
            placeholder="請簡述你的思考過程...",
            required=True
        ))
        
        # 欄位 3: 最終答案
        self.add_item(ui.InputText(
            label="最終答案",
            style=discord.InputTextStyle.short,
            placeholder="在此輸入最終結果",
            required=True
        ))
        # 🔥 [進階版] 轉換函式：將複雜的 LaTeX 數學題轉為人類可讀文字
    def format_latex_to_unicode(self, text):
        if not text: return ""
        
        # 1. 處理區塊公式 \[ ... \] -> 換行 + 縮排
        # 讓公式自己獨立一行，比較好讀
        text = text.replace(r'\[', '\n  ').replace(r'\]', '\n')
        text = text.replace(r'\(', '').replace(r'\)', '') # 移除行內公式標記

        # 2. 處理分數 \frac{a}{b} -> (a/b)
        # 這比較複雜，我們用簡單的邏輯：把 \frac{...}{...} 變成 (.../...)
        # 這裡只處理簡單結構，太複雜的巢狀分數可能需要更強的正則表達式
        text = re.sub(r'\\frac\{(.+?)\}\{(.+?)\}', r'(\1 / \2)', text)
        text = text.replace(r'\frac{1}{2}', '1/2') # 常見的 1/2 直接替換

        # 3. 處理數學符號 (擴充版)
        replacements = {
            r'\angle': '∠',
            r'\triangle': '△',
            r'\circ': '°',
            r'\theta': 'θ',
            r'\pi': 'π',
            r'\le': '≤',
            r'\ge': '≥',
            r'\neq': '≠',
            r'\approx': '≈',
            r'\times': '×',
            r'\div': '÷',
            r'\cdot': '·',
            r'\pm': '±',
            r'\infty': '∞',
            r'\rightarrow': '→',
            r'\cos': 'cos',  # 移除斜線
            r'\sin': 'sin',
            r'\tan': 'tan',
            r'\sqrt': '√',
        }
        
        for latex, char in replacements.items():
            text = text.replace(latex, char)

        # 4. 處理下標 (例如 S_2 -> S₂)
        # 把 _ 後面的數字轉成下標
        subscripts = {'0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉', 'n': 'ₙ'}
        for char, sub in subscripts.items():
            text = text.replace(f'_{char}', sub)      # 處理 _2
            text = text.replace(f'_{{{char}}}', sub)  # 處理 _{2}
            
        # 5. 處理上標 (例如 ^2 -> ²)
        superscripts = {'0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'}
        for char, sup in superscripts.items():
            text = text.replace(f'^{char}', sup)      # 處理 ^2
            text = text.replace(f'^{{{char}}}', sup)  # 處理 ^{2}

        # 6. 最後清理殘留的 LaTeX 語法
        text = text.replace('{', '').replace('}', '') # 移除花括號
        text = text.replace('\\', '') # 移除剩下的反斜線
        
        # 7. 加上分項符號優化 (讓條列式更清楚)
        text = text.replace('- ', '• ') 

        return text.strip()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # 注意：因為多了一個欄位，現在 children 的順序變了
        # children[0] 是題目 (我們不需要存這個)
        thought_process = self.children[1].value
        final_answer = self.children[2].value
        
        await handle_n8n_backend(
            interaction.message,
            N8N_EXAM_WEBHOOK_URL,
            action="submit_answer",
            extra_data={
                "task_index": self.task_index,
                "thought_process": thought_process,
                "final_answer": final_answer,
                "input_type": "modal"
            }
        )
        await interaction.followup.send(f"✅ **答案已提交！** AI 教練正在批改中...", ephemeral=True)
# EXAM_MODEL - view: 學習室專用的鷹架工具列
class ExamToolsView(ui.View):
    def __init__(self, task_index, question_text=""):
        super().__init__(timeout=None)
        self.task_index = task_index
        self.question_text = question_text # 把傳進來的題目存起來

    # 按鈕 A: 請求提示 (n8n 可以設定：答題模式按提示要扣分)
    @ui.button(label="💡 索取提示 (可能會扣分)", style=discord.ButtonStyle.secondary, custom_id="btn_exam_hint")
    async def hint_button(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        # 呼叫 n8n，Action 依然是 request_hint，但 n8n 可以根據 Thread 標題區分這是測驗
        await handle_n8n_backend(
            interaction.message,
            N8N_EXAM_WEBHOOK_URL,
            action="request_hint",
            extra_data={"task_index": self.task_index, "mode": "exam"}
        )

    # 按鈕 B: 卡關求救
    @ui.button(label="🙋 我卡住了", style=discord.ButtonStyle.danger, custom_id="btn_exam_stuck")
    async def stuck_button(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        await handle_n8n_backend(
            interaction.message,
            N8N_EXAM_WEBHOOK_URL,
            action="student_stuck",
            extra_data={"task_index": self.task_index, "mode": "exam"}
        )

    # 按鈕 C: 提交答案 (這會叫出原本寫好的 AnswerInputModal)
    @ui.button(label="✍️ 提交答案", style=discord.ButtonStyle.success, emoji="📝")
    async def submit_btn(self, button: ui.Button, interaction: discord.Interaction):
        # 🔥 把題目傳進 Modal
        await interaction.response.send_modal(
            AnswerInputModal(self.task_index, self.question_text)
        )


# EXAM_MODEL - view: 任務選擇
class ExamSelectView(ui.View):
    def __init__(self, task_options):
        super().__init__(timeout=70)
        self.task_options = task_options 
        
        select = ui.Select(
            placeholder="請選擇您要挑戰結案的任務...",
            options=[
                discord.SelectOption(
                    description=opt.get('description', '')[:100], # 防止過長報錯
                    value=str(opt['value']),
                    label=opt['label']          
                ) for opt in task_options
            ]
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        # 1. 為了避免使用者覺得沒反應，先 defer
        await interaction.response.defer(ephemeral=True)
        
        selected_value = self.children[0].values[0]
        selected_task_data = next(
            (item for item in self.task_options if str(item['value']) == selected_value), 
            None
        )
        full_content = selected_task_data.get('full_content') or selected_task_data.get('label')

        thread = None
        try:
            # =================================================
            # 🚀 步驟 1 (修正)：先建立考場 (Thread)，拿到 thread_id
            # =================================================
            thread_name = f"🧠 [答題中] {full_content[:10]}... (測驗)"
            thread = await interaction.channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                auto_archive_duration=1440
            )
            await thread.add_user(interaction.user)
            
            # 在考場內先發個訊息安撫使用者 (UX 優化)
            loading_msg = await thread.send(f"🤖 **AI 考官正在閱讀教材並為您出題中... (約需 10-20 秒)**")

            # =================================================
            # 🚀 步驟 2：呼叫 n8n (現在有 thread.id 了！)
            # =================================================
            quiz_question = "（題目生成失敗，請檢查 n8n）"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    N8N_EXAM_WEBHOOK_URL, 
                    json={
                        "action": "generate_quiz",
                        "user_id": str(interaction.user.id),
                        "task_index": selected_value,
                        "task_content": full_content,
                        "thread_id": str(thread.id)  # ✅ 這裡終於可以傳 ID 了
                    }, 
                    timeout=60.0 
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # 支援多種回傳欄位名稱
                    quiz_question = data.get("quiz_content") or data.get("reply") or data.get("output") or data.get("quiz_question")
                else:
                    print(f"n8n Quiz Gen Error: {response.status_code}")
                    await thread.send(f"❌ 出題失敗 (錯誤碼: {response.status_code})")
                    return

            # =================================================
            # 🚀 步驟 3：更新介面顯示題目
            # =================================================
            embed = discord.Embed(
                title="📝 結案挑戰：即時測驗",
                description=f"**針對任務：** {full_content}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"**❓ 題目：**\n\n"
                            f"{quiz_question}\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"您可以索取提示，完成後請點擊「提交答案」。",
                color=0xFFA500
            )
            
            # 刪除原本的 Loading 訊息，發送正式題目
            await loading_msg.delete()
            
            # 掛載正確的 ExamToolsView
            await thread.send(
                embed=embed, 
                view=ExamToolsView(
                    task_index=selected_value, 
                    question_text=quiz_question
                )
            )

            # 通知使用者跳轉
            await interaction.followup.send(f"✅ 題目已生成！請進入考場作答：<#{thread.id}>", ephemeral=True)

        except Exception as e:
            print(f"Error in select_callback: {e}")
            await interaction.followup.send(f"❌ 系統錯誤: {e}", ephemeral=True)

# ============================================================
# Discord slash 指令
# ============================================================

# 註冊指令
@bot.slash_command(name="register", description="註冊 SRL 學習助教帳號")
async def register(ctx: discord.ApplicationContext):
    # 1. 先顯示處理中 (因為 check_user_registered 需要連線 N8N)
    await ctx.defer(ephemeral=True)

    try:
        # 2. 檢查是否已經註冊
        is_reg = await check_user_registered(str(ctx.author.id))
        
        if is_reg:
            # 3A. 如果已註冊，直接告知
            await ctx.followup.send(
                "✅ **您已經完成註冊囉！**\n"
                "無需重複註冊，請直接使用 `/start_plan` 或 `/show_guide` 開始學習。",
                ephemeral=True
            )
        else:
            # 3B. 如果未註冊，顯示註冊按鈕 (RegisterView)
            # 因為 Modal 必須由按鈕互動觸發 (在 defer 之後)
            await ctx.followup.send(
                "👋 **歡迎來到 SRL 自主學習系統！**\n\n"
                "請點擊下方按鈕填寫基本資料，完成後即可解鎖所有功能。",
                view=RegisterView(),
                ephemeral=True
            )

    except Exception as e:
        await ctx.followup.send(f"❌ 系統檢查失敗：{e}", ephemeral=True)

# 學習室指令
@bot.slash_command(name="start_study", description="開始執行學習任務")
async def start_study(ctx: discord.ApplicationContext):
    await ctx.defer(ephemeral=True)

    try:
        # 1. 呼叫 n8n 獲取任務清單
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                N8N_GET_TASKS_URL,
                params={"user_id": str(ctx.author.id)},
                timeout=70.0
            )
            resp.raise_for_status()
            data = resp.json()
            options = data.get("options", [])

            if not options:
                await ctx.respond("您目前沒有未完成的任務。請輸入 `/start_plan`規劃新的學習計畫。", ephemeral=True)
                return

            # 2. 顯示下拉選單
            view = TaskSelectView(options)
            await ctx.respond("👇 請選擇您現在想要攻克的任務：", view=view, ephemeral=True)

    except Exception as e:
        await ctx.respond(f"❌ 無法獲取任務清單: {e}", ephemeral=True)

# 出題指令
@bot.slash_command(name="start_exam", description="[答題模式] 提交任務結案挑戰")
async def start_exam(ctx: discord.ApplicationContext):
    # 1. 先回應 defer，避免 N8N 拉取清單太久導致超時
    await ctx.defer(ephemeral=True)

    try:
        # 2. 呼叫 n8n 獲取任務清單 (GET)
        # 這裡維持用 GET 拉取清單，比較快且單純
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                N8N_GET_TASKS_URL,
                params={
                    "user_id": str(ctx.author.id),
                    "mode": "exam" # 告訴 n8n 過濾掉已完成的，或標記狀態
                },
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            options = data.get("options", [])

            # 3. 檢查是否有任務
            if not options:
                await ctx.respond("📭 您目前沒有進行中的任務，無法啟動測驗。", ephemeral=True)
                return

            # 4. 顯示下拉選單 (這裡呼叫更新版的 View)
            view = ExamSelectView(options)
            await ctx.respond("👇 **請選擇您要挑戰結案的任務：**", view=view, ephemeral=True)

    except httpx.RequestError as e:
        await ctx.respond(f"❌ 連線失敗 (N8N): {e}", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"❌ 發生未預期的錯誤: {e}", ephemeral=True)


# 計劃設計指令
@bot.slash_command(name="start_plan", description="在您的專屬頻道中開啟學習計畫對話")
async def start_plan_command(ctx: discord.ApplicationContext):
    # 1. 先檢查註冊
    is_reg = await check_user_registered(str(ctx.author.id))
    
    if not is_reg:
        # 如果沒註冊，顯示註冊按鈕
        await ctx.respond("👋 初次見面！在使用之前，請先完成簡單的註冊。", view=RegisterView(), ephemeral=True)
        return
    
    await ctx.defer(ephemeral=True)
    
    user_id = ctx.author.id
    user_name = ctx.author.name
    current_channel = ctx.channel # 這裡的 channel 是指令被輸入的頻道

    # 1. 建立一個專門用於規劃的 Thread (確保隱私)
    try:
        thread_name = f"📝 [規劃中] 本次學習計畫設計 "
        thread = await current_channel.create_thread(
            name=thread_name,
            type=discord.ChannelType.private_thread,
            auto_archive_duration=1440
        )
        await thread.add_user(ctx.author)
        # 先給使用者一個回應，告訴他去哪裡看
        # 這樣使用者知道 Thread 已經建好了，正在等 AI 說話
        await ctx.followup.send(f"✅ 規劃對話已在 <#{thread.id}> 啟動，**正在讀取您的歷史計畫...**", ephemeral=True)

        # 啟動規劃對話
        # 這樣使用者點進去就不會看到一片空白，知道 AI 正在工作
        loading_msg = await thread.send("🔄 **AI 教練正在讀取您的歷史學習檔案並分析中，請稍候...**")
        
        # [核心] 直接呼叫 n8n Planner API 獲取第一個引導問題
        payload = {
            "user_id": str(user_id),
            "user_name": user_name,
            "thread_id": str(thread.id),
            "channel_id": str(ctx.channel.id)
        }
        async with httpx.AsyncClient() as client:
            # ⏳ 這裡改回 await，並設定 60秒 timeout (足夠應付 14秒)
            response = await client.post(N8N_PLANNER_WEBHOOK_URL, json=payload, timeout=60.0)
            response.raise_for_status() # 如果 n8n 報錯 (4xx, 5xx)，這裡會直接跳到 except
            
            # 6. 解析 n8n 回傳的 JSON
            data = response.json()
            ai_reply = data.get("reply") # 取得 Agent 的開場白
            
            # 🚀 7. [UX 優化] 收到回應後，先把剛剛的「過場訊息」刪除
            # 這樣畫面比較乾淨，不會留下一堆系統提示
            try:
                await loading_msg.delete()
            except:
                pass # 如果刪除失敗(例如被手動刪了)也沒關係，繼續執行
            
            # 8. 發送 AI 的正式開場白
            if ai_reply:
                await thread.send(ai_reply)
            else:
                await thread.send(f"嗨 {ctx.author.mention}，我是您的學習教練！(AI 未回傳文字)")

    except httpx.TimeoutException:
        # 如果超時，也要記得把 loading 訊息改掉或刪除
        try: await loading_msg.delete()
        except: pass
        await thread.send("⚠️ AI 腦力激盪過久... 連線逾時。請直接在此輸入您的想法，我們會繼續開始規劃。")
        logging.error("Plan Init Timeout")
        
    except Exception as e:
        await ctx.followup.send(f"❌ 啟動失敗：{e}", ephemeral=True)
        logging.error(f"Start Plan Error: {e}")

        # --- 硬寫 ---
        # initial_question = (
        #     "好的，讓我們開始規劃。**請先設定您今天最想完成的具體學習目標** (例如：掌握餘弦定理公式)。"
        # )

    #     await thread.send(f"你好 {ctx.author.mention}！\n\n**SRL 規劃教練已上線。**\n\n{initial_question}")
        
    #     await ctx.respond(f"✅ 規劃對話已在 <#{thread.id}> 啟動，請前往查看。", ephemeral=True)
        
    # except Exception as e:
    #     await ctx.respond(f"❌ 規劃啟動失敗，請確保 Bot 權限足夠。錯誤：{e}", ephemeral=True)

# 查看學生狀態指令
@bot.slash_command(name="my_stats", description="查看我的學習任務進度")
async def my_stats(ctx: discord.ApplicationContext):
    # 1. 先檢查註冊
    is_reg = await check_user_registered(str(ctx.author.id))
    
    if not is_reg:
        # 如果沒註冊，顯示註冊按鈕
        await ctx.respond("👋 初次見面！在使用之前，請先完成簡單的註冊。", view=RegisterView(), ephemeral=True)
        return
    await ctx.defer(ephemeral=True)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                N8N_STATS_API_URL, 
                params={"user_id": str(ctx.author.id)}, 
                timeout=70.0
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("has_data"):
                await ctx.respond("📊 您目前還沒有建立學習計畫。請輸入 `/start_plan` 開始。", ephemeral=True)
                return

            embed = discord.Embed(
                title="📊 個人學習儀表板",
                description=data.get("text_summary"),
                color=0x28a745, # 綠色代表進度
                timestamp=discord.utils.utcnow()
            )
            
            # 將圖表放在右上角縮圖 (適合甜甜圈圖)
            chart_url = data.get("chart_url")
            # 加入這行來除錯，看看 n8n 到底傳了什麼鬼東西過來
            print(f"[DEBUG] Received Chart URL: {chart_url}")
            if chart_url and isinstance(chart_url, str) and chart_url.startswith("http"):
                embed.set_thumbnail(url=chart_url)
            else:
                print("[WARNING] Chart URL 無效，已跳過圖片顯示。")

            embed.set_footer(text="保持節奏，繼續前進！🚀")

            await ctx.respond(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"Stats Error: {e}")
        await ctx.respond("❌ 獲取數據失敗，請稍後再試。", ephemeral=True)

# 指令: /show_guide 置頂學習指南
@bot.slash_command(name="show_guide", description="顯示學習功能說明書")
async def show_guide(ctx: discord.ApplicationContext):
    # 這是公開訊息，不用 ephemeral
    
    # 1. 設計 Embed 內容
    embed = discord.Embed(
        title="🎓 SRL 學習助教：完全使用指南",
        description=(
            "歡迎來到自主學習頻道！本助手將協助您完成 **「準備 ➔ 執行 ➔ 反思」** 的高效學習循環。\n"
            "請參考以下步驟開始您的學習之旅："
        ),
        color=0x00b0f4 # 天藍色
    )

    # 區塊 0: 準備工作
    embed.add_field(
        name="🌱 第一步：準備與規劃 (Preparation)",
        value=(
            "**`/upload_textbook`**\n"
            "📂 **上傳教材**：支援 PDF 格式。上傳後系統會自動建立索引，讓 AI 讀懂您的課本。\n"
            "**`/start_plan`**\n"
            "🗓️ **擬定計畫**：與 AI 教練對話，將教材拆解為具體的「待辦任務」，並設定學習策略。"
        ),
        inline=False
    )

    # 區塊 1: 執行學習
    embed.add_field(
        name="🔥 第二步：執行與監控 (Performance)",
        value=(
            "**`/start_study`**\n"
            "📖 **學習室 (讀書模式)**：\n"
            "進入專注狀態。您可以隨時向 AI 提問、釐清觀念。完成學習後點擊「✅ 完成任務」，系統會自動生成學習日誌。\n\n"
            "**`/start_exam`**\n"
            "⚔️ **測驗室 (挑戰模式)**：\n"
            "當您認為已經精通某個任務時，請來此挑戰！AI 會即時出題考核，這是證明實力與獲取高分的唯一途徑。"
        ),
        inline=False
    )

    # 區塊 2: 成果反思
    embed.add_field(
        name="📊 第三步：反思與調整 (Reflection)",
        value=(
            "**`/my_result`**\n"
            "📝 **查看單次成果**：查詢特定任務的 AI 詳細評語、強弱項分析與總結。\n"
            "**`/my_stats`**\n"
            "📈 **個人儀表板**：查看長期的學習進度條、累積積分與能力雷達圖。"
        ),
        inline=False
    )
    
    # 底部提示
    embed.add_field(
        name="💡 小貼士",
        value="• 首次使用請留意私訊，完成簡單註冊。\n• 學習室與測驗室皆具備 **自動記錄** 功能，請放心學習。",
        inline=False
    )
    
    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/4712/4712009.png") # 您的 Logo

    try:
        # 2. 發送訊息
        response = await ctx.respond(embed=embed)

        # 3. 執行釘選 (Pin)
        message = await response.original_response()
        await message.pin(reason="SRL 學習指南置頂")
        
        # 4. 悄悄告訴老師成功了
        await ctx.followup.send("✅ 指南已更新並自動釘選！", ephemeral=True)

    except discord.Forbidden:
        await ctx.respond("❌ 錯誤：Bot 缺少 `Manage Messages` (管理訊息) 權限，無法釘選。", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"❌ 發生錯誤：{e}", ephemeral=True)


# 學習結果確認指令: /my_result 
@bot.slash_command(name="my_result", description="查看我的學習任務結果與 AI 點評")
async def my_result(ctx: discord.ApplicationContext, task_index: str = None):
    """
    獲取學生的學習成果摘要與詳細對話歷史
    """
    # 1. 檢查註冊狀態 (延用你原本的函式)
    is_reg = await check_user_registered(str(ctx.author.id))
    if not is_reg:
        await ctx.respond("👋 請先完成註冊後再查詢結果。", view=RegisterView(), ephemeral=True)
        return

    await ctx.defer(ephemeral=True)
    
    user_id = ctx.author.id

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GET_RESULT_URL, 
                json={"user_id": str(user_id)}, 
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()

            # 提取資料庫欄位
            reflection = data.get("reflection_text") or "尚未完成結案反思。"
            score_trend = data.get("score_trend") or [] # 陣列紀錄 [40, 60, 80]
            task_name = data.get("task_content") or f"任務 {task_index if task_index else '最新'}"

            # 建立主卡片
            embed = discord.Embed(
                title=f"📊 學習成效報告：{task_name}",
                color=0x2ecc71 if data.get("current_score", 0) >= 60 else 0xe74c3c
            )
            
            # 分數趨勢顯示
            embed.add_field(
                name="📈 挑戰歷程", 
                value=f"**{data.get('score_trend')}**\n", 
                inline=False
            )

            # 顯示統計數據
            embed.add_field(
                name="📊 統計資訊", 
                value=f"最後結果：{data.get('status_label')}\n", 
                inline=False
            )
            
            # AI 點評 (reflection_text)
            embed.add_field(name="🧠 AI 教練總結點評", value=f"{reflection}", inline=False)

            await ctx.respond(embed=embed)

    except Exception as e:
        await ctx.respond(f"❌ 查詢失敗：無法從後端獲取數據。", ephemeral=True)
        logging.error(f"My Result Error: {e}")

import urllib.parse
# 上傳教材指令
@bot.slash_command(name="upload_textbook", description="上傳教材 PDF 並設定 Task ID")
async def upload_textbook(
    ctx: discord.ApplicationContext,
    file: discord.Attachment, # Pycord 會自動將其轉為檔案上傳選項
    # task_id: str              # Pycord 會自動將其轉為文字輸入選項
    custom_name: str = None  # 可選的自訂檔名參數
):
    # 1. 先檢查註冊 (維持既有設計)
    is_reg = await check_user_registered(str(ctx.author.id))
    
    if not is_reg:
        await ctx.respond("👋 初次見面！在使用之前，請先完成簡單的註冊。", view=RegisterView(), ephemeral=True)
        return

    # 2. 檢查檔案格式
    if not file.filename.lower().endswith('.pdf'):
        await ctx.respond("❌ 錯誤：僅支援 PDF 格式！請重新上傳。", ephemeral=True)
        return

    # 3. 立即回應 (Defer) 避免超時
    # 這裡 ephemeral=False 可以讓大家看到上傳了什麼，或者設 True 保持隱私
    await ctx.defer(ephemeral=False) 

    final_filename = file.filename # 預設值

    if custom_name:
        # A. 如果使用者有輸入自訂名稱，直接用它 (記得補上 .pdf)
        final_filename = custom_name.strip()
        if not final_filename.lower().endswith('.pdf'):
            final_filename += ".pdf"
    else:
        # B. 如果沒輸入，嘗試從 URL 救救看 (雖然依您的狀況可能無效，但留著當備案)
        try:
            raw_url_name = file.url.split('/')[-1].split('?')[0]
            decoded_name = urllib.parse.unquote(raw_url_name)
            if len(decoded_name) > len(file.filename): # 如果解析出來的比較長，通常代表救回來了
                final_filename = decoded_name
        except:
            pass # 解析失敗就維持原樣

    try:
        # 4. 準備 Payload
        payload = {
            "user_id": str(ctx.author.id),
            "user_name": ctx.author.name,
            "channel_id": str(ctx.channel.id), # 紀錄是在哪個頻道上傳的
            "file_url": file.url,        # Discord 的 CDN 下載連結
            "file_name": final_filename,
            "file_size": file.size
            # "task_id": task_id           # 用戶輸入的 Task ID(先不用)
        }

        # 5. 發送至 n8n (使用 httpx，符合您原本的設計)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                N8N_Upload_URL, 
                json=payload, 
                timeout=70.0 # 上傳處理可能較久，設定長一點的 timeout
            )
            
            # 檢查 HTTP 狀態碼
            if response.status_code == 200:
                # 成功回傳
                await ctx.followup.send(
                    f"✅ **上傳成功！**\n"
                    f"📂 檔案：`{final_filename}`\n"
                    # f"🏷️ Task ID：`{task_id}`\n"
                    f"後端正在建立索引中，稍後即可針對此教材提問。"
                )
            else:
                # n8n 回傳非 200 錯誤
                await ctx.followup.send(f"⚠️ 上傳失敗，n8n 回傳錯誤碼：{response.status_code}")

    except httpx.RequestError as e:
        await ctx.followup.send(f"❌ 連線失敗：無法聯繫 n8n 伺服器。", ephemeral=True)
        logging.error(f"Upload API Error: {e}")
    except Exception as e:
        await ctx.followup.send(f"❌ 發生未預期的錯誤：{e}", ephemeral=True)
        logging.error(f"Upload Command Unknown Error: {e}")

# --- 指令：我的筆記 ---
@bot.slash_command(name="my_notes", description="打開我的雲端筆記櫃")
async def my_notes(ctx):
    await ctx.defer(ephemeral=True)
    
    try:
        # 1. 呼叫 N8N 列出檔案
        async with httpx.AsyncClient() as client:
            response = await client.get(
                N8N_READ_URL,
                params={
                    "action": "list_files", 
                    "channel_id": str(ctx.channel.id),
                    "user_id": str(ctx.author.id) # 用名字去搜檔名
                },
                timeout=30.0
            )
        
        if response.status_code == 200:
            data = response.json() 
            # 假設 N8N 回傳結構: {"files": [{"id": "xxx", "name": "xxx"}, ...]}
            files = data.get("files", [])

            if not files:
                await ctx.followup.send("📭 您目前還沒有任何筆記喔！快去學習室寫幾篇吧。", ephemeral=True)
            else:
                await ctx.followup.send(
                    f"📚 找到 {len(files)} 篇筆記，請選擇：", 
                    view=NoteListView(files), # 👈 只要傳 files 就好！
                    ephemeral=True
                )
        else:
            await ctx.followup.send(f"⚠️ 無法取得列表 (N8N Error: {response.status_code})", ephemeral=True)

    except Exception as e:
        await ctx.followup.send(f"❌ 發生錯誤: {e}", ephemeral=True)

# ------------------------------------------------------------------
# 🧠 事件監聽器 (核心橋接)
# ------------------------------------------------------------------

@bot.event
async def on_message(message: discord.Message):
    # 忽略 Bot 自己的訊息
    if message.author.bot: # 更安全的方式是檢查 .bot 屬性
        return

    # 檢查是否為「私密答題討論串」中的訊息
    if isinstance(message.channel, discord.Thread):
        thread_name = message.channel.name

        if thread_name.startswith("📝 [規劃中]"):
            # 情況二：規劃對話邏輯
            await handle_n8n_backend(message, N8N_PLANNER_WEBHOOK_URL)

        # 針對學習室的路由
        # 針對學習室的路由
        elif thread_name.startswith("🚀 [學習中]"):
            t_id = str(message.channel.id)
            # 檢查這個 Thread 目前是否正在進行審核
            current_action = thread_status.get(t_id) # 如果沒設過，會是 None (即一般對話)
            
            # 傳送當前的 action 給 n8n
            await handle_n8n_backend(
                message, 
                N8N_LEARNING_WEBHOOK_URL, 
                action=current_action
            )

    # 確保其他指令能正常運作
    await bot.process_commands(message)

# ------------------------------------------------------------------
# 🚀 啟動
# ------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"✅ Bot {bot.user} 已經上線 (Hybrid Mode)")
    await bot.sync_commands()

bot.run(BOT_TOKEN)