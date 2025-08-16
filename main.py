import discord
from discord.ext import commands
import os
import asyncio
import yt_dlp as youtube_dl
from dotenv import load_dotenv
import random
import functools
import sys
import subprocess

# Load environment variables
load_dotenv()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# YouTube DL options
ytdl_format_options = {
    'format': 'bestaudio[ext=m4a]/best[ext=mp4]/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -filter:a "volume=0.5"'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')
        self.thumbnail = data.get('thumbnail', 'https://i.imgur.com/8QZQZ.png')
        self.duration = data.get('duration', 0)

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        
        to_run = functools.partial(ytdl.extract_info, url, download=not stream)
        try:
            data = await loop.run_in_executor(None, to_run)
        except Exception as e:
            print(f"Error extracting info: {e}")
            raise e
        
        if 'entries' in data:
            data = data['entries'][0]
        
        if stream:
            filename = data['url']
        else:
            filename = ytdl.prepare_filename(data)
        
        print(f"Playing: {data.get('title')} - URL: {filename}")
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

# Music queue for each guild
music_queues = {}

class MusicQueue:
    def __init__(self):
        self.queue = []
        self.current = None
        self.volume = 0.5
        self.loop_current = False
        self.loop_queue = False

    def add(self, song):
        self.queue.append(song)

    def get_next(self):
        if self.queue:
            return self.queue.pop(0)
        return None

    def clear(self):
        self.queue.clear()
        self.current = None

    def shuffle(self):
        random.shuffle(self.queue)

# Helper function to automatically join user's voice channel
async def ensure_voice_connection(ctx):
    """Ensure bot is connected to the user's voice channel"""
    if not ctx.author.voice:
        embed = discord.Embed(
            title="Voice Channel Required",
            description="You need to be in a voice channel to use music commands!",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
        return False
    
    user_channel = ctx.author.voice.channel
    
    if not ctx.voice_client:
        try:
            await user_channel.connect()
            if ctx.guild.id not in music_queues:
                music_queues[ctx.guild.id] = MusicQueue()
            
            embed = discord.Embed(
                title="Voice Channel Joined",
                description=f"Automatically connected to **{user_channel.name}**",
                color=0x51cf66
            )
            await ctx.send(embed=embed)
            return True
        except Exception as e:
            embed = discord.Embed(
                title="Connection Failed",
                description=f"Couldn't join voice channel: {str(e)}",
                color=0xff6b6b
            )
            await ctx.send(embed=embed)
            return False
    
    elif ctx.voice_client.channel != user_channel:
        try:
            await ctx.voice_client.move_to(user_channel)
            embed = discord.Embed(
                title="Voice Channel Moved",
                description=f"Moved to **{user_channel.name}**",
                color=0x51cf66
            )
            await ctx.send(embed=embed)
            return True
        except Exception as e:
            embed = discord.Embed(
                title="Move Failed",
                description=f"Couldn't move to voice channel: {str(e)}",
                color=0xff6b6b
            )
            await ctx.send(embed=embed)
            return False
    
    return True

# Bot events
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is ready and connected to {len(bot.guilds)} servers')
    await bot.change_presence(activity=discord.Game(name="Music Bot | !help for commands"))

@bot.event
async def on_voice_state_update(member, before, after):
    """Handle voice state updates to disconnect bot when alone"""
    if member == bot.user:
        return
    
    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)
    if voice_client and voice_client.channel:
        if len(voice_client.channel.members) == 1:
            await asyncio.sleep(30)
            if len(voice_client.channel.members) == 1:
                await voice_client.disconnect()
                if member.guild.id in music_queues:
                    music_queues[member.guild.id].clear()

# Voice commands
@bot.command(name='join')
async def join(ctx):
    """Join the voice channel"""
    if not ctx.author.voice:
        embed = discord.Embed(
            title="Voice Channel Required",
            description="You need to be in a voice channel first!",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
        return
    
    try:
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            if ctx.voice_client.channel == channel:
                embed = discord.Embed(
                    title="Already Connected",
                    description="I'm already in your voice channel!",
                    color=0x4ecdc4
                )
                await ctx.send(embed=embed)
                return
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        
        if ctx.guild.id not in music_queues:
            music_queues[ctx.guild.id] = MusicQueue()
        
        embed = discord.Embed(
            title="Voice Channel Joined",
            description=f"Successfully connected to **{channel.name}**",
            color=0x51cf66
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="Connection Failed",
            description=f"Couldn't join voice channel: {str(e)}",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)

@bot.command(name='leave', aliases=['disconnect'])
async def leave(ctx):
    """Leave the voice channel"""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        if ctx.guild.id in music_queues:
            music_queues[ctx.guild.id].clear()
        
        embed = discord.Embed(
            title="Voice Channel Left",
            description="Successfully disconnected from voice channel",
            color=0xffa94d
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Not Connected",
            description="I'm not currently in a voice channel!",
            color=0xff8787
        )
        await ctx.send(embed=embed)

# Music commands
@bot.command(name='play', aliases=['p'])
async def play(ctx, *, search=None):
    """Play a song from YouTube"""
    if not search:
        embed = discord.Embed(
            title="Search Required",
            description="Please provide a song name or YouTube URL to play!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.guild.id not in music_queues:
        music_queues[ctx.guild.id] = MusicQueue()
    
    queue = music_queues[ctx.guild.id]
    
    try:
        async with ctx.typing():
            if not search.startswith(('http://', 'https://')):
                search = f"ytsearch:{search}"
            
            player = await YTDLSource.from_url(search, loop=bot.loop, stream=True)
            
            song_info = {'player': player, 'ctx': ctx, 'requester': ctx.author}
            
            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                queue.add(song_info)
                embed = discord.Embed(
                    title="Song Added to Queue",
                    description=f"**{player.title}**",
                    color=0x51cf66
                )
                embed.add_field(name="Position in Queue", value=f"#{len(queue.queue)}", inline=True)
                embed.add_field(name="Requested by", value=ctx.author.mention, inline=True)
                if player.thumbnail:
                    embed.set_thumbnail(url=player.thumbnail)
                await ctx.send(embed=embed)
            else:
                queue.current = song_info
                try:
                    def after_playing(error):
                        if error:
                            print(f'Player error: {error}')
                        else:
                            coro = play_next(ctx)
                            fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
                            try:
                                fut.result()
                            except:
                                pass
                    
                    ctx.voice_client.play(player, after=after_playing)
                    await now_playing(ctx)
                except Exception as e:
                    print(f"Error starting playback: {e}")
                    embed = discord.Embed(
                        title="Playback Error",
                        description=f"Failed to start playing: {str(e)}",
                        color=0xff6b6b
                    )
                    await ctx.send(embed=embed)
                
    except Exception as e:
        embed = discord.Embed(
            title="Song Load Error",
            description=f"Failed to load song: {str(e)}",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
        print(f"Error in play command: {e}")

async def play_next(ctx):
    """Play the next song in queue"""
    if ctx.guild.id not in music_queues:
        return
    
    queue = music_queues[ctx.guild.id]
    
    if ctx.voice_client and ctx.voice_client.is_connected():
        next_song = queue.get_next()
        
        if next_song:
            queue.current = next_song
            try:
                def after_playing(error):
                    if error:
                        print(f'Player error: {error}')
                    else:
                        coro = play_next(ctx)
                        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
                        try:
                            fut.result()
                        except:
                            pass
                
                ctx.voice_client.play(next_song['player'], after=after_playing)
                await now_playing(ctx)
            except Exception as e:
                print(f"Error playing next song: {e}")
                await asyncio.sleep(1)
                asyncio.create_task(play_next(ctx))
        else:
            queue.current = None

@bot.command(name='skip', aliases=['s'])
async def skip(ctx):
    """Skip the current song"""
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
        embed = discord.Embed(
            title="Song Skipped",
            description="Successfully skipped to the next song",
            color=0x51cf66
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Nothing Playing",
            description="There's nothing currently playing to skip!",
            color=0xff8787
        )
        await ctx.send(embed=embed)

@bot.command(name='pause')
async def pause(ctx):
    """Pause the current song"""
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        embed = discord.Embed(
            title="Music Paused",
            description="Playback has been paused",
            color=0xffd43b
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Nothing Playing",
            description="There's nothing currently playing to pause!",
            color=0xff8787
        )
        await ctx.send(embed=embed)

@bot.command(name='resume', aliases=['unpause'])
async def resume(ctx):
    """Resume the paused song"""
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        embed = discord.Embed(
            title="Music Resumed",
            description="Playback has been resumed",
            color=0x51cf66
        )
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(
            title="Nothing Paused",
            description="There's nothing currently paused to resume!",
            color=0xff8787
        )
        await ctx.send(embed=embed)

@bot.command(name='stop')
async def stop(ctx):
    """Stop playing and clear queue"""
    if not await ensure_voice_connection(ctx):
        return
    
    if ctx.guild.id in music_queues:
        music_queues[ctx.guild.id].clear()
    
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        ctx.voice_client.stop()
    
    embed = discord.Embed(
        title="Music Stopped",
        description="Playback stopped and queue cleared",
        color=0xff6b6b
    )
    await ctx.send(embed=embed)

# Queue management
@bot.command(name='queue', aliases=['q'])
async def show_queue(ctx):
    """Show the current queue"""
    if ctx.guild.id not in music_queues:
        embed = discord.Embed(
            title="Queue Empty",
            description="The music queue is currently empty!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    queue = music_queues[ctx.guild.id]
    
    embed = discord.Embed(title="Music Queue", color=0x339af0)
    
    if queue.current:
        current_song = queue.current['player']
        embed.add_field(
            name="Now Playing", 
            value=f"**[{current_song.title}]({current_song.url})**\nRequested by: {queue.current['requester'].mention}",
            inline=False
        )
    
    if queue.queue:
        queue_text = ""
        total_duration = 0
        for i, song in enumerate(queue.queue[:10], 1):
            duration = song['player'].duration if song['player'].duration else 0
            total_duration += duration
            duration_str = f"{duration//60}:{duration%60:02d}" if duration > 0 else "Unknown"
            queue_text += f"`{i}.` **{song['player'].title[:40]}{'...' if len(song['player'].title) > 40 else ''}** `[{duration_str}]`\n"
        
        if len(queue.queue) > 10:
            queue_text += f"... and **{len(queue.queue) - 10}** more songs"
        
        embed.add_field(name="Up Next", value=queue_text, inline=False)
        
        total_duration_str = f"{total_duration//3600}:{(total_duration%3600)//60:02d}:{total_duration%60:02d}"
        embed.set_footer(text=f"Total songs in queue: {len(queue.queue)} | Total duration: {total_duration_str}")
    else:
        embed.add_field(name="Up Next", value="Queue is empty", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='nowplaying', aliases=['np'])
async def now_playing(ctx):
    """Show the currently playing song"""
    if ctx.guild.id not in music_queues or not music_queues[ctx.guild.id].current:
        embed = discord.Embed(
            title="Nothing Playing",
            description="No music is currently playing!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    queue = music_queues[ctx.guild.id]
    current = queue.current['player']
    requester = queue.current['requester']
    
    embed = discord.Embed(title="Now Playing", color=0x339af0)
    embed.add_field(name="Title", value=f"**[{current.title}]({current.url})**", inline=False)
    embed.add_field(name="Requested by", value=requester.mention, inline=True)
    
    if current.duration:
        duration_str = f"{current.duration//60}:{current.duration%60:02d}"
        embed.add_field(name="Duration", value=duration_str, inline=True)
    
    queue_length = len(queue.queue)
    if queue_length > 0:
        embed.add_field(name="Songs in Queue", value=str(queue_length), inline=True)
    
    if current.thumbnail:
        embed.set_thumbnail(url=current.thumbnail)
    
    await ctx.send(embed=embed)

@bot.command(name='shuffle')
async def shuffle_queue(ctx):
    """Shuffle the current queue"""
    if ctx.guild.id not in music_queues:
        embed = discord.Embed(
            title="Queue Empty",
            description="The music queue is currently empty!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    queue = music_queues[ctx.guild.id]
    if not queue.queue:
        embed = discord.Embed(
            title="Queue Empty",
            description="The music queue is currently empty!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    queue.shuffle()
    embed = discord.Embed(
        title="Queue Shuffled",
        description=f"Successfully shuffled **{len(queue.queue)}** songs in the queue",
        color=0x51cf66
    )
    await ctx.send(embed=embed)

# Message management
@bot.command(name='clear', aliases=['purge'])
@commands.has_permissions(manage_messages=True)
async def clear_messages(ctx, amount: int = 1):
    """Delete specified number of messages (default: 1)"""
    try:
        amount = max(1, min(amount, 100))
        
        await ctx.message.delete()
        deleted = await ctx.channel.purge(limit=amount)
        
        embed = discord.Embed(
            title="Messages Cleared",
            description=f"Successfully deleted **{len(deleted)}** messages",
            color=0x51cf66
        )
        msg = await ctx.send(embed=embed)
        await asyncio.sleep(3)
        await msg.delete()
    except discord.Forbidden:
        embed = discord.Embed(
            title="Permission Denied",
            description="I don't have permission to delete messages in this channel!",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="Delete Failed",
            description=f"Failed to delete messages: {str(e)}",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)

# Help command
@bot.command(name='help')
async def help_command(ctx):
    """Show all available commands"""
    embed = discord.Embed(
        title="Music Bot Commands",
        description="Complete command guide for the music bot",
        color=0x339af0
    )
    
    embed.add_field(
        name=">> Voice Commands",
        value="`!join` - Join your voice channel\n"
              "`!leave` or `!disconnect` - Leave voice channel",
        inline=False
    )
    
    embed.add_field(
        name=">> Music Commands (Auto-joins your channel)",
        value="`!play <query>` or `!p <query>` - Play a song from YouTube\n"
              "`!pause` - Pause current song\n"
              "`!resume` or `!unpause` - Resume paused song\n"
              "`!skip` or `!s` - Skip current song\n"
              "`!stop` - Stop playing and clear queue",
        inline=False
    )
    
    embed.add_field(
        name=">> Queue Management",
        value="`!queue` or `!q` - Show current music queue\n"
              "`!nowplaying` or `!np` - Show currently playing song\n"
              "`!shuffle` - Shuffle the current queue",
        inline=False
    )
    
    embed.add_field(
        name=">> Utility Commands",
        value="`!clear <amount>` or `!purge <amount>` - Delete messages (Admin Only)\n"
              "`!say <message>` - Send message in simple embed\n"
              "`!embed <content>` or `!e <content>` - Create custom embeds\n"
              "`!embedhelp` or `!ehelp` - Show embed formatting help",
        inline=False
    )
    
    embed.add_field(
        name=">> Admin Commands (Owner Only)",
        value="`!announce <message>` - Send announcement embed\n"
              "`!shutdown` - Shutdown the bot\n"
              "`!restart` - Restart the bot automatically",
        inline=False
    )
    
    embed.add_field(
        name=">> Additional Information",
        value="**Music Sources:** YouTube links or search terms\n"
              "**Auto-Features:** Auto-join voice channels, auto-leave when alone\n"
              "**Embed Colors:** red, green, blue, yellow, orange, purple, pink, cyan, gray, black",
        inline=False
    )
    
    embed.set_footer(text="Use the ! prefix for all commands")
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
    
    await ctx.send(embed=embed)
    
    embed.add_field(
        name="Additional Information",
        value="**Music Sources:** YouTube links or search terms\n"
              "**Auto-Features:** Auto-join voice channels, auto-leave when alone\n"
              "**Embed Colors:** red, green, blue, yellow, orange, purple, pink, cyan, gray, black",
        inline=False
    )
    
    embed.set_footer(text="Use the ! prefix for all commands")
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else None)
    
    await ctx.send(embed=embed)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="Missing Argument",
            description="You're missing a required argument! Use `!help` for help.",
            color=0xff8787
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="Permission Denied",
            description="You don't have permission to use this command!",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.BotMissingPermissions):
        embed = discord.Embed(
            title="Bot Permission Missing",
            description="I don't have the required permissions to execute this command!",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)
    else:
        print(f"Error in {ctx.command}: {error}")
        embed = discord.Embed(
            title="Command Error",
            description=f"An unexpected error occurred: {str(error)}",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)

# Cleanup on shutdown
@bot.event
async def on_disconnect():
    for guild_id in music_queues:
        music_queues[guild_id].clear()

# Owner-only commands
def is_owner():
    def predicate(ctx):
        OWNER_ID = int(os.getenv('OWNER_ID', '0'))
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)

@bot.command(name='shutdown')
@is_owner()
async def shutdown(ctx):
    """Shutdown the bot (Owner only)"""
    embed = discord.Embed(
        title="Bot Shutting Down",
        description="The bot is shutting down... Goodbye!",
        color=0xff6b6b
    )
    await ctx.send(embed=embed)
    
    # Disconnect from all voice channels
    for voice_client in bot.voice_clients:
        await voice_client.disconnect()
    
    # Clear all queues
    for guild_id in music_queues:
        music_queues[guild_id].clear()
    
    print(f"Bot shutdown initiated by {ctx.author}")
    await bot.close()

@bot.command(name='restart')
@is_owner()
async def restart(ctx):
    """Restart the bot (Owner only) - Windows compatible"""
    embed = discord.Embed(
        title=">> Bot Restarting",
        description="The bot is restarting now... Please wait a moment!",
        color=0xffa94d
    )
    await ctx.send(embed=embed)
    
    # Disconnect from all voice channels
    for voice_client in bot.voice_clients:
        await voice_client.disconnect()
    
    # Clear all queues
    for guild_id in music_queues:
        music_queues[guild_id].clear()
    
    print(f"Bot restart initiated by {ctx.author}")
    
    # Close the bot connection
    await bot.close()
    
    # Restart the script using subprocess for Windows
    try:
        # Get the current Python executable and script path
        python_executable = sys.executable
        script_path = os.path.abspath(__file__)
        
        print("Restarting bot...")
        
        # Use subprocess to restart the bot on Windows
        subprocess.Popen([python_executable, script_path], 
                        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        
        # Exit the current process
        os._exit(0)
        
    except Exception as e:
        print(f"Failed to restart: {e}")
        print("Please manually restart the bot.")
        os._exit(1)

@bot.command(name='announce')
@is_owner()
async def announce(ctx, *, message=None):
    """Send a message in an embed (Owner only)"""
    if not message:
        embed = discord.Embed(
            title="Message Required",
            description="Please provide a message to announce!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    try:
        await ctx.message.delete()
        
        embed = discord.Embed(
            title="Announcement",
            description=message,
            color=0x339af0
        )
        embed.set_footer(text=f"Announced by {ctx.author.display_name}")
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        embed = discord.Embed(
            title="Permission Error",
            description="I don't have permission to delete messages!",
            color=0xff6b6b
        )
        await ctx.send(embed=embed)

@bot.command(name='say')
async def say(ctx, *, message=None):
    """Send a message in an embed"""
    if not message:
        embed = discord.Embed(
            title="Message Required",
            description="Please provide a message to send!",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    try:
        await ctx.message.delete()
        
        embed = discord.Embed(
            description=message,
            color=0x51cf66
        )
        embed.set_footer(text=f"Message by {ctx.author.display_name}")
        await ctx.send(embed=embed)
        
    except discord.Forbidden:
        embed = discord.Embed(
            description=message,
            color=0x51cf66
        )
        embed.set_footer(text=f"Message by {ctx.author.display_name}")
        await ctx.send(embed=embed)

@bot.command(name='embed', aliases=['e'])
async def embed_message(ctx, *, content=None):
    """Create a custom embed with your message"""
    if not content:
        embed = discord.Embed(
            title="Content Required",
            description="Please provide content for the embed!\n\n**Usage Examples:**\n"
                       "`!embed Hello World` - Simple message\n"
                       "`!embed title:Welcome | description:This is a welcome message` - Custom title and description\n"
                       "`!embed title:Alert | description:Important news | color:red` - With custom color",
            color=0xff8787
        )
        await ctx.send(embed=embed)
        return
    
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass
    
    # Parse the content for custom formatting
    title = None
    description = content
    color = 0x339af0
    
    if '|' in content:
        parts = [part.strip() for part in content.split('|')]
        for part in parts:
            if part.startswith('title:'):
                title = part[6:].strip()
            elif part.startswith('description:'):
                description = part[12:].strip()
            elif part.startswith('color:'):
                color_name = part[6:].strip().lower()
                color_map = {
                    'red': 0xff6b6b,
                    'green': 0x51cf66,
                    'blue': 0x339af0,
                    'yellow': 0xffd43b,
                    'orange': 0xffa94d,
                    'purple': 0x9775fa,
                    'pink': 0xff8cc8,
                    'cyan': 0x4ecdc4,
                    'gray': 0x868e96,
                    'black': 0x2d3436
                }
                color = color_map.get(color_name, 0x339af0)
    
    # Create and send the embed
    embed = discord.Embed(color=color)
    
    if title:
        embed.title = title
        if description and description != content:
            embed.description = description
    else:
        embed.description = description
    
    embed.set_footer(text=f"Embedded by {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
    embed.timestamp = ctx.message.created_at
    
    await ctx.send(embed=embed)

@bot.command(name='embedhelp', aliases=['ehelp'])
async def embed_help(ctx):
    """Show help for the embed command"""
    embed = discord.Embed(
        title=">> Embed Command Help",
        description="Create beautiful embedded messages with custom formatting!",
        color=0x339af0
    )
    
    embed.add_field(
        name=">> Basic Usage",
        value="`!embed Your message here`\n"
              "Creates a simple embed with your message",
        inline=False
    )
    
    embed.add_field(
        name=">> Advanced Usage",
        value="`!embed title:Your Title | description:Your description`\n"
              "`!embed title:Alert | description:Important message | color:red`",
        inline=False
    )
    
    embed.add_field(
        name=">> Available Colors",
        value="red, green, blue, yellow, orange, purple, pink, cyan, gray, black",
        inline=False
    )
    
    embed.add_field(
        name=">> Examples",
        value="`!embed Welcome to our server!`\n"
              "`!embed title:Announcement | description:Server maintenance tonight | color:yellow`\n"
              "`!embed title:Rules | description:Be respectful to everyone | color:green`",
        inline=False
    )
    
    embed.set_footer(text="Use !embed or !e for short")
    await ctx.send(embed=embed)

# Run the bot
if __name__ == "__main__":
    token = os.getenv('DISCORD_BOT_TOKEN')
    if not token:
        print("Error: DISCORD_BOT_TOKEN not found in environment variables!")
        print("Please create a .env file with your bot token:")
        print("DISCORD_BOT_TOKEN=your_bot_token_here")
        print("OWNER_ID=your_discord_user_id_here")
    else:
        try:
            bot.run(token)
        except Exception as e:
            print(f"Failed to start bot: {e}")
            print("Make sure your bot token is correct and the bot has proper permissions.")