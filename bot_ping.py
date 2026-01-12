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


bot.run(TOKEN)
