import os
import json
import re
import datetime
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
from threading import Thread

# ----------------------------------------------------
# 1. FLASK WEB SERVER (24/7 Hosting Keep Alive)
# ----------------------------------------------------
app = Flask('')

@app.route('/')
def home():
    return "PRISM Moderation Bot is 24/7 Active!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# ----------------------------------------------------
# 2. DATA STORAGE MANAGEMENT (JSON file)
# ----------------------------------------------------
DATA_FILE = "prism_config.json"

DEFAULT_DATA = {
    "guilds": {}
}

def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, indent=4)
        return DEFAULT_DATA
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

prism_data = load_data()

def get_guild_config(guild_id: str):
    g_id = str(guild_id)
    if g_id not in prism_data["guilds"]:
        prism_data["guilds"][g_id] = {
            "log_channel_id": None,
            "warn_rules": {},  # e.g., "3": {"action": "timeout", "duration": 10}
            "user_warns": {},   # e.g., "user_id": 2
            "blacklisted_words": {} # e.g., "word": "1_min_tm"
        }
        save_data(prism_data)
    return prism_data["guilds"][g_id]

# ----------------------------------------------------
# 3. DISCORD BOT SETUP & LOGGING HELPER
# ----------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class PRISMBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("PRISM Slash commands synced globally.")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

bot = PRISMBot()

# Embed Colors
COLOR_PRISM = discord.Color.from_rgb(142, 68, 173)
COLOR_WARN = discord.Color.gold()
COLOR_DANGER = discord.Color.red()
COLOR_SUCCESS = discord.Color.green()

async def send_mod_log(guild: discord.Guild, title: str, description: str, fields: dict = None):
    config = get_guild_config(guild.id)
    log_channel_id = config.get("log_channel_id")
    if not log_channel_id:
        return

    channel = guild.get_channel(log_channel_id)
    if channel:
        embed = discord.Embed(
            title=f"🛡️ PRISM LOGS | {title}",
            description=description,
            color=COLOR_PRISM,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        if fields:
            for name, val in fields.items():
                embed.add_field(name=name, value=val, inline=False)
        embed.set_footer(text="PRISM Moderation System")
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

# Permission Error Handler
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        embed = discord.Embed(
            title="🚫 Access Denied",
            description="You do not have the required permissions to run this command!",
            color=COLOR_DANGER
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        print(f"Command Error: {error}")

# ----------------------------------------------------
# 4. AUTO-MODERATION (BLWORD MONITORING)
# ----------------------------------------------------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    config = get_guild_config(message.guild.id)
    blwords = config.get("blacklisted_words", {})

    if not blwords:
        await bot.process_commands(message)
        return

    content_lower = message.content.lower()

    for word, punishment in blwords.items():
        if re.search(rf"\b{re.escape(word)}\b", content_lower):
            try:
                await message.delete()
            except Exception:
                pass

            punishment_text = "Message Blocked"
            duration = None

            if punishment == "1_min_tm":
                duration = datetime.timedelta(minutes=1)
                punishment_text = "1 Minute Timeout"
            elif punishment == "5_min_tm":
                duration = datetime.timedelta(minutes=5)
                punishment_text = "5 Minutes Timeout"
            elif punishment == "10_min_tm":
                duration = datetime.timedelta(minutes=10)
                punishment_text = "10 Minutes Timeout"

            if duration and isinstance(message.author, discord.Member):
                try:
                    await message.author.timeout(duration, reason=f"Triggered blacklisted word: '{word}'")
                except Exception:
                    pass

            embed = discord.Embed(
                title="⚠️ Blacklisted Word Detected",
                description=f"{message.author.mention}, your message contained a blacklisted word and was removed.",
                color=COLOR_DANGER
            )
            embed.add_field(name="Action Taken", value=f"`{punishment_text}`")
            await message.channel.send(embed=embed, delete_after=6)

            await send_mod_log(
                guild=message.guild,
                title="Blacklisted Word Triggered",
                description=f"User {message.author.mention} (`{message.author.id}`) triggered word filter.",
                fields={
                    "Word": f"`{word}`",
                    "Punishment": f"`{punishment_text}`",
                    "Channel": message.channel.mention
                }
            )
            break

    await bot.process_commands(message)

# ----------------------------------------------------
# 5. MODERATION COMMANDS
# ----------------------------------------------------

# (1) WARN COMMAND
@bot.tree.command(name="warn", description="Warn a user for violating rules.")
@app_commands.checks.has_permissions(moderate_members=True) # Requires Timeout Users Perm
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if user.bot:
        await interaction.response.send_message("❌ You cannot warn a bot.", ephemeral=True)
        return

    config = get_guild_config(interaction.guild.id)
    user_id_str = str(user.id)
    
    current_warns = config["user_warns"].get(user_id_str, 0) + 1
    config["user_warns"][user_id_str] = current_warns
    save_data(prism_data)

    embed = discord.Embed(
        title="⚠️ User Warned",
        description=f"**{user.mention}** has been issued a warning.",
        color=COLOR_WARN
    )
    embed.add_field(name="Total Warns", value=f"`{current_warns}`", inline=True)
    embed.add_field(name="Reason", value=f"`{reason}`", inline=True)
    await interaction.response.send_message(embed=embed)

    await send_mod_log(
        guild=interaction.guild,
        title="User Warned",
        description=f"Moderator {interaction.user.mention} warned {user.mention}.",
        fields={"Reason": reason, "Total Warns": str(current_warns)}
    )

    warn_rules = config.get("warn_rules", {})
    rule = warn_rules.get(str(current_warns))
    
    if rule:
        action = rule.get("action")
        duration = rule.get("duration", 0)

        try:
            if action == "timeout":
                td = datetime.timedelta(minutes=duration)
                await user.timeout(td, reason=f"Reached threshold of {current_warns} warnings.")
                action_desc = f"Timed out for `{duration}` minutes."
            elif action == "kick":
                await user.kick(reason=f"Reached threshold of {current_warns} warnings.")
                action_desc = "Kicked from the server."
            elif action == "ban":
                await user.ban(reason=f"Reached threshold of {current_warns} warnings.")
                action_desc = "Permanently banned from the server."

            await interaction.channel.send(f"🚨 **Auto-Punishment Triggered**: {user.mention} was **{action_desc}**")
            await send_mod_log(
                guild=interaction.guild,
                title="Automated Threshold Punishment Executed",
                description=f"User {user.mention} triggered auto-action for reaching `{current_warns}` warnings.",
                fields={"Action": action_desc}
            )
        except Exception as e:
            await interaction.channel.send(f"⚠️ Failed to apply automated punishment: `{e}`")


# (2) SETUP WARN SYSTEM COMMAND (🔒 ADMIN ONLY)
@bot.tree.command(name="setup-warn-system", description="Configure automated punishments for warning thresholds.")
@app_commands.checks.has_permissions(administrator=True) # 🔒 Admin Only
@app_commands.choices(action=[
    app_commands.Choice(name="Timeout", value="timeout"),
    app_commands.Choice(name="Kick", value="kick"),
    app_commands.Choice(name="Ban", value="ban")
])
async def setup_warn_system(
    interaction: discord.Interaction, 
    warn_count: int, 
    action: app_commands.Choice[str], 
    duration_minutes: int = 0
):
    config = get_guild_config(interaction.guild.id)
    
    config["warn_rules"][str(warn_count)] = {
        "action": action.value,
        "duration": duration_minutes
    }
    save_data(prism_data)

    duration_text = f" ({duration_minutes} mins)" if action.value == "timeout" else ""
    
    embed = discord.Embed(
        title="⚙️ Warning Threshold Configured",
        description=f"Reaching **{warn_count} warning(s)** will now automatically execute a **{action.name}{duration_text}**.",
        color=COLOR_SUCCESS
    )
    await interaction.response.send_message(embed=embed)


# (3) KICK COMMAND
@bot.tree.command(name="kick", description="Kick a member from the server.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    await user.kick(reason=reason)
    
    embed = discord.Embed(
        title="👢 Member Kicked",
        description=f"**{user.name}** (`{user.id}`) was kicked from the server.",
        color=COLOR_DANGER
    )
    embed.add_field(name="Reason", value=reason)
    await interaction.response.send_message(embed=embed)

    await send_mod_log(
        guild=interaction.guild,
        title="Member Kicked",
        description=f"Moderator {interaction.user.mention} kicked {user.name}.",
        fields={"Reason": reason}
    )


# (4) SOFT BAN COMMAND
@bot.tree.command(name="soft_ban", description="Ban a user for a set duration of time (in minutes).")
@app_commands.checks.has_permissions(ban_members=True)
async def soft_ban(interaction: discord.Interaction, user: discord.User, duration_minutes: int, reason: str = "No reason provided"):
    await interaction.guild.ban(user, reason=f"Soft-ban ({duration_minutes} mins): {reason}")
    
    embed = discord.Embed(
        title="⏳ Member Soft-Banned",
        description=f"**{user.name}** was banned for **{duration_minutes} minutes**.",
        color=COLOR_WARN
    )
    embed.add_field(name="Reason", value=reason)
    await interaction.response.send_message(embed=embed)

    await send_mod_log(
        guild=interaction.guild,
        title="Member Soft-Banned",
        description=f"Moderator {interaction.user.mention} soft-banned {user.name} for {duration_minutes} mins.",
        fields={"Reason": reason}
    )

    async def temp_unban():
        import asyncio
        await asyncio.sleep(duration_minutes * 60)
        try:
            await interaction.guild.unban(user, reason="Soft-ban duration expired.")
            await send_mod_log(
                guild=interaction.guild,
                title="Soft-Ban Expired",
                description=f"User **{user.name}** was automatically unbanned."
            )
        except Exception:
            pass

    import asyncio
    asyncio.create_task(temp_unban())


# (5) PERMANENT BAN COMMAND
@bot.tree.command(name="ban", description="Permanently ban a user from the server.")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, user: discord.User, reason: str = "No reason provided"):
    await interaction.guild.ban(user, reason=reason)
    
    embed = discord.Embed(
        title="🔨 Member Permanently Banned",
        description=f"**{user.name}** (`{user.id}`) was permanently banned.",
        color=COLOR_DANGER
    )
    embed.add_field(name="Reason", value=reason)
    await interaction.response.send_message(embed=embed)

    await send_mod_log(
        guild=interaction.guild,
        title="Member Permanently Banned",
        description=f"Moderator {interaction.user.mention} permanently banned {user.name}.",
        fields={"Reason": reason}
    )


# (6) SETUP LOGS COMMAND (🔒 ADMIN ONLY)
@bot.tree.command(name="setup_logs", description="Set the official PRISM logs channel.")
@app_commands.checks.has_permissions(administrator=True)
async def setup_logs(interaction: discord.Interaction, channel: discord.TextChannel):
    config = get_guild_config(interaction.guild.id)
    config["log_channel_id"] = channel.id
    save_data(prism_data)

    embed = discord.Embed(
        title="📜 Audit Logs Channel Set",
        description=f"PRISM moderation logs will now be posted in {channel.mention}.",
        color=COLOR_SUCCESS
    )
    await interaction.response.send_message(embed=embed)


# (7) BLWORD ADD COMMAND (🔒 ADMIN ONLY)
@bot.tree.command(name="blword", description="Add comma-separated blacklisted words and set their punishment.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(punishment=[
    app_commands.Choice(name="Block Message Only", value="block"),
    app_commands.Choice(name="1 Min Timeout", value="1_min_tm"),
    app_commands.Choice(name="5 Min Timeout", value="5_min_tm"),
    app_commands.Choice(name="10 Min Timeout", value="10_min_tm")
])
async def blword(interaction: discord.Interaction, words: str, punishment: app_commands.Choice[str]):
    config = get_guild_config(interaction.guild.id)
    
    word_list = [w.strip().lower() for w in words.split(",") if w.strip()]
    
    for word in word_list:
        config["blacklisted_words"][word] = punishment.value

    save_data(prism_data)

    words_formatted = ", ".join([f"`{w}`" for w in word_list])
    embed = discord.Embed(
        title="🚫 Blacklist Words Added",
        description=f"Added blacklisted words: {words_formatted}",
        color=COLOR_SUCCESS
    )
    embed.add_field(name="Punishment", value=f"`{punishment.name}`")
    await interaction.response.send_message(embed=embed)


# (8) BLWORD REMOVE COMMAND (🔒 ADMIN ONLY)
@bot.tree.command(name="blword_remove", description="Remove a word from the blacklist.")
@app_commands.checks.has_permissions(administrator=True)
async def blword_remove(interaction: discord.Interaction, word: str):
    config = get_guild_config(interaction.guild.id)
    target_word = word.strip().lower()

    if target_word in config["blacklisted_words"]:
        del config["blacklisted_words"][target_word]
        save_data(prism_data)

        embed = discord.Embed(
            title="✅ Word Removed from Blacklist",
            description=f"Removed **`{target_word}`** from auto-moderation.",
            color=COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"❌ The word **`{target_word}`** was not found in the blacklist.", ephemeral=True)


# ----------------------------------------------------
# RUN BOT
# ----------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv("DISCORD_TOKEN")
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN is missing!")