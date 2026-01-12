import os, discord
from discord.ext import commands



TOKEN = os.getenv("Discord_token")
GUILD_ID = str(os.getenv("Discord_guild_id"))

intents = discord.Intents.default()
intents.message_content = True          #設置可得到訊息內容

# client = discord.Client(intents=intents)
bot = commands.Bot(command_prefix="!", intents=intents)       #暫時設置 "!"開頭的為命令，非官方的"/"

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

# 設置遊戲的dc ui
class PlayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)   #設置不會超時

    @discord.ui.button(label="剪刀", style=discord.ButtonStyle.green, custom_id="scissors")
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content = "你出了剪刀")

    @discord.ui.button(label="石頭", style=discord.ButtonStyle.green, custom_id="rock")
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content = "你出了石頭")

    @discord.ui.button(label="布", style=discord.ButtonStyle.green, custom_id="paper")
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content = "你出了布")

    @discord.ui.button(label="取消", style=discord.ButtonStyle.red, custom_id="cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content = "取消遊戲....", view=None)

# 設置遊戲
@bot.hybrid_command()
async def play(ctx):
    """開始遊戲"""
    await ctx.send("開始猜拳", view=PlayView())

bot.run(TOKEN)
