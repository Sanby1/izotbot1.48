import asyncio
from datetime import datetime, timedelta
import json
import os
import random
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
import os

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.messages = True
intents.message_content = True
intents.reactions = True
intents.moderation = True
intents.voice_states = True

user_message_history = {}
SPAM_THRESHOLD = 4
SPAM_TIMEFRAME = timedelta(seconds=10)
MUTE_DURATION = timedelta(days=1)

COMMAND_CHANNEL_NAME = "§🤖bot-commands"
GIVEAWAY_CHANNEL_NAME = "§🎁giveaway"
invite_cache = {}


DATA_FILE = "server_data.json"
user_message_counts = {}
user_voice_time = {}
user_voice_start_time = {}


voice_system_data = {}  # {guild_id_str: creator_voice_channel_id}
temp_voice_channels = {} # {temp_voice_channel_id_str: owner_user_id_str}


giveaways = {}

def load_data():
    global user_message_counts, user_voice_time, voice_system_data, temp_voice_channels, giveaways
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

                loaded_messages = data.get("messages", {})
                for g_id, users in loaded_messages.items():
                    g_id_int = int(g_id)
                    if g_id_int not in user_message_counts:
                        user_message_counts[g_id_int] = {}
                    for u_id, count in users.items():
                        user_message_counts[g_id_int][int(u_id)] = count

                loaded_voice = data.get("voice", {})
                for g_id, users in loaded_voice.items():
                    g_id_int = int(g_id)
                    if g_id_int not in user_voice_time:
                        user_voice_time[g_id_int] = {}
                    for u_id, dur in users.items():
                        user_voice_time[g_id_int][int(u_id)] = dur
                
                voice_system_data.update(data.get("voice_system_data", {}))
                temp_voice_channels.update(data.get("temp_voice_channels", {}))
                
           
                loaded_giveaways = data.get("giveaways", {})
                giveaways.clear()
                for msg_id, g_data in loaded_giveaways.items():
                    giveaways[int(msg_id)] = g_data

            print("💾 Database loaded successfully! / Veritabanı başarıyla yüklendi!")
        except Exception as e:
            print(f"Data load error / Veri yükleme hatası: {e}")

def save_data():
    now = time.time()
    for g_id, users in list(user_voice_start_time.items()):
        for u_id, start_t in list(users.items()):
            duration = now - start_t
            if duration > 0:
                if g_id not in user_voice_time:
                    user_voice_time[g_id] = {}
                user_voice_time[g_id][u_id] = (user_voice_time[g_id].get(u_id, 0) + duration)
            user_voice_start_time[g_id][u_id] = now

    data = {
        "messages": user_message_counts, 
        "voice": user_voice_time,
        "voice_system_data": voice_system_data,
        "temp_voice_channels": temp_voice_channels,
        "giveaways": giveaways 
    }

    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Data save error / Veri kaydetme hatası: {e}")


bot = commands.Bot(command_prefix="!", intents=intents)


# --- Commands Cog ---
class CommandsCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.number_guess_games = {}
        self.check_giveaways.start() 

    def cog_unload(self):
        self.check_giveaways.cancel()

    
    @tasks.loop(seconds=15)
    async def check_giveaways(self):
        """Her 15 saniyede bir bitmiş çekiliş var mı diye kontrol eder."""
        now = time.time()
        to_end = []
        for msg_id, data in list(giveaways.items()):
            if now >= data["end_time"]:
                to_end.append(msg_id)
        
        for msg_id in to_end:
            await self.end_giveaway(msg_id)

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # ÖZEL ODA SİSTEMİ KOMUTLARI (VOICE)
    # ==========================================
    
    voice = app_commands.Group(name="voice", description="Özel oda yönetim komutları")

    @voice.command(name="oda-kurulum", description="[Admin] Özel oda sistemini (kategori, kanallar, yazı) sunucuya kurar.")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_voice_system(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild

        category = await guild.create_category("Özel Odanı Kur")
        info_channel = await guild.create_text_channel("🔒özel-oda-kullanım", category=category)
        await guild.create_text_channel("🤖özel-oda-komut", category=category)
        creator_vc = await guild.create_voice_channel("🔊Özel Oda Oluştur", category=category)

        voice_system_data[str(guild.id)] = creator_vc.id
        save_data()

        embed = discord.Embed(title="Oda Açma Komutları", color=0x2b2d31)
        embed.description = """
        **/voice lock** | *Kanalı kilitler. Yani izin vermediğiniz kişiler kanalınıza giremez.*
        **/voice unlock** | *Kanalın kilidini açar. Yani herkes girebilir.*
        **/voice name name:<isim>** | *Odanın adını değiştirmenizi sağlar.*
        **/voice limit limit:<sayı>** | *Sayı girmeniz durumunda odanız için kişi sayısı limiti belirler.*
        **/voice permit mention:<etiket>** | *Odanızı kilitlediğinizde odanıza birinin girebilmesi için yetki verir.*
        **/voice reject mention:<etiket>** | *Odanızdan istemediğiniz kişileri engellemek için kullanabileceğiniz komut.*
        **/voice claim** | *Odanın asıl sahibi çıkarsa, odanın yetkilerini devralmanızı sağlayan komut.*
        """
        
        msg_content = f"# 🔒özel-oda-kullanım kanalına hoş geldin!\n# 🔒özel-oda-kullanım kanalının doğuşu!"
        await info_channel.send(content=msg_content, embed=embed)
        await interaction.followup.send(f"✅ Özel oda sistemi başarıyla kuruldu! Kategori ve kanallar hazırlandı.")

    async def check_voice_owner(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            await interaction.response.send_message("❌ Bir ses kanalında değilsin!", ephemeral=True)
            return None
        
        vc_id_str = str(vc.id)
        if vc_id_str not in temp_voice_channels:
            await interaction.response.send_message("❌ Bulunduğun kanal, senin kurduğun özel bir oda değil!", ephemeral=True)
            return None
            
        if temp_voice_channels[vc_id_str] != str(interaction.user.id):
            await interaction.response.send_message("❌ Bu özel odanın sahibi sen değilsin!", ephemeral=True)
            return None
            
        return vc

    @voice.command(name="lock", description="Odanızı kilitler.")
    async def v_lock(self, interaction: discord.Interaction):
        vc = await self.check_voice_owner(interaction)
        if not vc: return
        overwrite = vc.overwrites_for(interaction.guild.default_role)
        overwrite.connect = False
        await vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔒 Odanız başarıyla kilitlendi. Dışarıdan kimse giremez.", ephemeral=True)

    @voice.command(name="unlock", description="Odanızın kilidini açar.")
    async def v_unlock(self, interaction: discord.Interaction):
        vc = await self.check_voice_owner(interaction)
        if not vc: return
        overwrite = vc.overwrites_for(interaction.guild.default_role)
        overwrite.connect = None
        await vc.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔓 Odanızın kilidi açıldı. Artık herkes katılabilir.", ephemeral=True)

    @voice.command(name="name", description="Odanızın adını değiştirir.")
    @app_commands.describe(name="Odanın yeni adı")
    async def v_name(self, interaction: discord.Interaction, name: str):
        vc = await self.check_voice_owner(interaction)
        if not vc: return
        await vc.edit(name=name)
        await interaction.response.send_message(f"✅ Odanın adı **{name}** olarak değiştirildi.", ephemeral=True)

    @voice.command(name="limit", description="Odanızın kullanıcı limitini belirler (Sınırsız için 0).")
    @app_commands.describe(limit="Kişi sayısı limiti (0-99)")
    async def v_limit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]):
        vc = await self.check_voice_owner(interaction)
        if not vc: return
        await vc.edit(user_limit=limit)
        limit_text = f"**{limit}** kişi" if limit > 0 else "Sınırsız"
        await interaction.response.send_message(f"👥 Odanızın limiti **{limit_text}** olarak ayarlandı.", ephemeral=True)

    @voice.command(name="permit", description="Kilitli odanıza özel birinin girmesine izin verir.")
    async def v_permit(self, interaction: discord.Interaction, mention: discord.Member):
        vc = await self.check_voice_owner(interaction)
        if not vc: return
        overwrite = vc.overwrites_for(mention)
        overwrite.connect = True
        await vc.set_permissions(mention, overwrite=overwrite)
        await interaction.response.send_message(f"✅ {mention.mention} kişisine odaya giriş izni verildi.", ephemeral=True)

    @voice.command(name="reject", description="Odanızdan birini atar ve girmesini yasaklar.")
    async def v_reject(self, interaction: discord.Interaction, mention: discord.Member):
        vc = await self.check_voice_owner(interaction)
        if not vc: return
        overwrite = vc.overwrites_for(mention)
        overwrite.connect = False
        await vc.set_permissions(mention, overwrite=overwrite)
        if mention in vc.members:
            await mention.move_to(None) # Odadan at
        await interaction.response.send_message(f"🚫 {mention.mention} kişisi odadan atıldı ve girmesi yasaklandı.", ephemeral=True)

    @voice.command(name="claim", description="Odanın kurucusu çıkmışsa odanın sahipliğini devralırsınız.")
    async def v_claim(self, interaction: discord.Interaction):
        vc = interaction.user.voice.channel if interaction.user.voice else None
        if not vc:
            return await interaction.response.send_message("❌ Bir ses kanalında değilsin!", ephemeral=True)
            
        vc_id_str = str(vc.id)
        if vc_id_str not in temp_voice_channels:
            return await interaction.response.send_message("❌ Bu kanal bir özel oda değil!", ephemeral=True)
            
        owner_id = temp_voice_channels[vc_id_str]
        
        if interaction.guild.get_member(int(owner_id)) in vc.members:
            return await interaction.response.send_message("❌ Odanın sahibi hala bu kanalda! Sahipliği devralamazsın.", ephemeral=True)
            
        temp_voice_channels[vc_id_str] = str(interaction.user.id)
        save_data()
        await interaction.response.send_message(f"👑 Başarılı! Artık bu odanın yeni sahibi sensin.", ephemeral=True)

    # ==========================================
    # GÜNCELLENMİŞ ÇEKİLİŞ SİSTEMİ (KALICI)
    # ==========================================

    @app_commands.command(name="giveaway-start", description="[TR] Çekiliş başlat | [EN] Starts a new giveaway.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        duration="[TR] Süre [EN] Duration (10s, 5m, 2h, 1d)",
        winner_count="[TR] Kazanan Sayısı [EN] Winners",
        prize="[TR] Ödül [EN] Prize",
        required_role="[Opsiyonel] Sadece bu role sahip olanlar kazanabilir."
    )
    async def giveaway_start(self, interaction: discord.Interaction, duration: str, winner_count: int, prize: str, required_role: discord.Role = None):
        giveaway_channel = discord.utils.get(interaction.guild.text_channels, name=GIVEAWAY_CHANNEL_NAME)
        if not giveaway_channel:
            return await interaction.response.send_message(f"❌ 🇹🇷 '{GIVEAWAY_CHANNEL_NAME}' kanalı bulunamadı!\n❌ 🇬🇧 Could not find '{GIVEAWAY_CHANNEL_NAME}' channel!", ephemeral=True)
        if interaction.channel.id != giveaway_channel.id:
            return await interaction.response.send_message(f"🇹🇷 Sadece {giveaway_channel.mention}!\n🇬🇧 Only in {giveaway_channel.mention}!", ephemeral=True)

        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        time_seconds = 0
        unit = duration[-1].lower()
        if unit in units:
            try:
                val = int(duration[:-1])
                if val <= 0: raise ValueError()
                time_seconds = val * units[unit]
            except ValueError:
                return await interaction.response.send_message("🇹🇷 Geçersiz süre formatı (Örn: 5m, 2h)\n🇬🇧 Invalid format (Ex: 5m, 2h)", ephemeral=True)
        else:
            return await interaction.response.send_message("🇹🇷 Geçersiz birim (s, m, h, d)\n🇬🇧 Invalid unit (s, m, h, d)", ephemeral=True)

        if winner_count <= 0:
            return await interaction.response.send_message("🇹🇷 Kazanan sayısı 0'dan büyük olmalı.\n🇬🇧 Winners must be positive.", ephemeral=True)

        # datetime yerine timestamp kullanıyoruz (JSON'a kolay yazmak için)
        end_timestamp = time.time() + time_seconds
        end_dt = datetime.fromtimestamp(end_timestamp).astimezone()
        
        role_text = f"\n🎯 **Özel Katılım Şartı:** Sadece {required_role.mention} rolüne sahip olanlar kazanabilir!" if required_role else "\n🎯 **Özel Katılım Şartı:** Yok (Herkes katılabilir!)"

        embed = discord.Embed(
            title=f"<a:party2:1364026112333840414> {prize} <a:party1:1364026108118302741>",
            description=(
                f"🇹🇷 Katılmak için <:gift1:1364436048142139524> emojisine tıkla!\n🇬🇧 Click <:gift1:1364436048142139524> to enter!\n"
                f"{role_text}\n\n"
                f"🏆 Kazananlar / Winners: **{winner_count}**\n⏳ Bitiş / Ends: {discord.utils.format_dt(end_dt, style='R')} ({discord.utils.format_dt(end_dt, style='F')})"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Hosted by: {interaction.user.display_name}")

        try:
            await interaction.response.send_message(embed=embed)
            message = await interaction.original_response()
            await message.add_reaction("<:gift1:1364436048142139524>")
        except Exception:
            try: await interaction.followup.send("Hata / Error", ephemeral=True)
            except: pass
            return

        # Artık kalıcı sözlüğe kaydediyoruz
        giveaways[message.id] = {
            "prize": prize,
            "end_time": end_timestamp,
            "winner_count": winner_count,
            "channel_id": interaction.channel.id,
            "host_id": interaction.user.id,
            "required_role_id": required_role.id if required_role else None
        }
        save_data() # Veritabanına anında yaz! Bot kapansa bile hatırlayacak.

    @giveaway_start.error
    async def giveaway_start_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("🇹🇷 Yetki yok. / 🇬🇧 No permission.", ephemeral=True)

    @app_commands.command(name="giveaway-end", description="[TR] Çekilişi erken bitir | [EN] Ends giveaway early.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_end_cmd(self, interaction: discord.Interaction, message_id: str):
        giveaway_channel = discord.utils.get(interaction.guild.text_channels, name=GIVEAWAY_CHANNEL_NAME)
        if not giveaway_channel:
            return await interaction.response.send_message(f"❌ '{GIVEAWAY_CHANNEL_NAME}' Not found / Bulunamadı", ephemeral=True)
        if interaction.channel.id != giveaway_channel.id:
            return await interaction.response.send_message(f"🇹🇷 Sadece {giveaway_channel.mention}!\n🇬🇧 Only in {giveaway_channel.mention}!", ephemeral=True)

        try:
            msg_id_int = int(message_id)
            success = await self.end_giveaway(msg_id_int, manually_ended_by=interaction.user)
            if success:
                await interaction.response.send_message(f"✅ Çekiliş bitiriliyor / Ending giveaway (ID: {message_id})...", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Çekiliş bulunamadı veya çoktan bitti. Eski bir mesajdan seçim yapmak istiyorsan **/giveaway-draw** komutunu kullan.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("🇹🇷 Geçersiz ID / 🇬🇧 Invalid ID", ephemeral=True)

    async def end_giveaway(self, message_id: int, manually_ended_by: discord.User = None):
        if message_id not in giveaways: return False

        giveaway_data = giveaways.pop(message_id)
        save_data() # Bittiğinde veritabanından sil.
        
        channel = self.bot.get_channel(giveaway_data["channel_id"])
        if not channel or not isinstance(channel, discord.TextChannel): return False

        try: message = await channel.fetch_message(message_id)
        except: return False

        raw_participants = []
        if message.reactions:
            for reaction in message.reactions:
                if str(reaction.emoji) == "<:gift1:1364436048142139524>":
                    try:
                        async for user in reaction.users():
                            if not user.bot:
                                member = channel.guild.get_member(user.id)
                                if member: raw_participants.append(member)
                    except: pass
                    break

        valid_participants = []
        req_role_id = giveaway_data.get("required_role_id")
        for p in raw_participants:
            if req_role_id:
                if discord.utils.get(p.roles, id=req_role_id):
                    valid_participants.append(p)
            else:
                valid_participants.append(p)

        winners = []
        winner_count = giveaway_data["winner_count"]

        if valid_participants:
            if len(valid_participants) <= winner_count: winners = valid_participants
            else: winners = random.sample(valid_participants, winner_count)

        result_msg_content = f"<a:party2:1364026112333840414> **{giveaway_data['prize']}** Giveaway Ended / Çekiliş Bitti! <a:party1:1364026108118302741>\n"
        if manually_ended_by: result_msg_content += f"(Ended early by / Erken bitiren: {manually_ended_by.mention}.)\n"

        if not raw_participants:
            result_msg_content += "\n🇹🇷 Katılım olmadı. <:Grr:1364026073599443067>\n🇬🇧 No participants."
        elif raw_participants and not valid_participants:
             result_msg_content += "\n🇹🇷 Katılımcılar vardı ancak gerekli role sahip kimse çıkmadı! ❌"
        elif not winners:
            result_msg_content += "\n🇹🇷 Kazanan belirlenemedi. / 🇬🇧 Could not determine winners."
        else:
            winner_mentions = ", ".join(w.mention for w in winners)
            result_msg_content += f"\n🏆 Kazananlar / Winners: {winner_mentions}\nTebrikler / Congrats! <a:gift:1364026079282593802>"

        try: await channel.send(content=result_msg_content, allowed_mentions=discord.AllowedMentions(users=winners))
        except: pass

        try:
            if message.embeds:
                original_embed = message.embeds[0]
                original_embed.title = f"Giveaway Ended / Bitti: {giveaway_data['prize']}"
                if winners:
                    winner_str = ", ".join(f"**{w.display_name}**" for w in winners)
                    original_embed.description = f"🇹🇷 Bu çekiliş bitti.\n🇬🇧 This giveaway has ended.\n\n🏆 Kazananlar / Winners: {winner_str}"
                else:
                    original_embed.description = "🇹🇷 Şartları sağlayan katılımcı olmadığı için kazanan yok.\n🇬🇧 No winners due to lack of valid participants."
                original_embed.color = discord.Color.dark_grey()
                original_embed.set_footer(text=f"Giveaway ID: {message_id} | Ended")
                original_embed.clear_fields()
                await message.edit(embed=original_embed, view=None)
            else:
                await message.edit(content=f"~~Giveaway: {giveaway_data['prize']}~~\nEnded / Bitti.", view=None)
        except: pass
        return True

    # ==========================================
    # MANUEL ÇEKİLİŞ ÇEKME (İSTEDİĞİN FALLBACK ÖZELLİĞİ)
    # ==========================================
    @app_commands.command(name="giveaway-draw", description="[TR] Belirli bir mesajdan manuel çekiliş seçer. (Yedek) | [EN] Manual draw from message.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        message_id="Çekilişin bulunduğu mesajın ID'si",
        winner_count="Kaç kazanan seçilecek?",
        required_role="Opsiyonel olarak bir rol seçebilirsiniz."
    )
    async def giveaway_draw(self, interaction: discord.Interaction, message_id: str, winner_count: int, required_role: discord.Role = None):
        giveaway_channel = discord.utils.get(interaction.guild.text_channels, name=GIVEAWAY_CHANNEL_NAME)
        if interaction.channel.id != giveaway_channel.id:
            return await interaction.response.send_message(f"🇹🇷 Sadece {giveaway_channel.mention} kanalında kullanabilirsin!", ephemeral=True)
            
        await interaction.response.defer(ephemeral=False)
        try:
            msg_id_int = int(message_id)
            message = await interaction.channel.fetch_message(msg_id_int)
        except Exception:
            return await interaction.followup.send("❌ Mesaj bulunamadı! Lütfen geçerli bir mesaj ID'si girin.")

        raw_participants = []
        if message.reactions:
            for reaction in message.reactions:
                if str(reaction.emoji) == "<:gift1:1364436048142139524>":
                    try:
                        async for user in reaction.users():
                            if not user.bot:
                                member = interaction.channel.guild.get_member(user.id)
                                if member: raw_participants.append(member)
                    except: pass
                    break

        valid_participants = []
        for p in raw_participants:
            if required_role:
                if discord.utils.get(p.roles, id=required_role.id):
                    valid_participants.append(p)
            else:
                valid_participants.append(p)

        winners = []
        if valid_participants:
            if len(valid_participants) <= winner_count: winners = valid_participants
            else: winners = random.sample(valid_participants, winner_count)

        if not winners:
            return await interaction.followup.send("❌ Gerekli şartları karşılayan kimse bulunamadığı için kazanan seçilemedi.")

        winner_mentions = ", ".join(w.mention for w in winners)
        result_msg = f"🎉 **MANUEL ÇEKİLİŞ SONUCU!** 🎉\nMesaj ID: `{message_id}`\n\n🏆 **Kazananlar:** {winner_mentions}\nTebrikler!"
        await interaction.followup.send(content=result_msg, allowed_mentions=discord.AllowedMentions(users=winners))

    # ==========================================
    # GENEL KOMUTLAR VE OYUNLAR 
    # ==========================================

    @app_commands.command(name="resetnames", description="[TR] İsimleri sıfırlar | [EN] Resets everyone's nickname.")
    @app_commands.checks.has_permissions(administrator=True)
    async def resetnames(self, interaction: discord.Interaction):
        await interaction.response.send_message("⏳ 🇹🇷 Tüm üyelerin takma adları sıfırlanıyor. (Yavaş işlem)\n⏳ 🇬🇧 Starting to reset all members' nicknames. (Slow process)", ephemeral=False)
        changed, errors = 0, 0
        for member in interaction.guild.members:
            if member.nick is not None:
                try:
                    await member.edit(nick=None, reason="Mass nickname reset command executed.")
                    changed += 1
                    await asyncio.sleep(1.5)
                except discord.Forbidden: errors += 1
                except Exception as e:
                    errors += 1
                    print(f"Nickname reset error: {e}")
        await interaction.followup.send(f"✅ 🇹🇷 İşlem Tamamlandı! **{changed}** kişinin adı sıfırlandı. (Hatalar: {errors})\n✅ 🇬🇧 Process Completed! **{changed}** nicknames reset. (Errors: {errors})")

    @resetnames.error
    async def resetnames_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ 🇹🇷 Bu komut için `Yönetici` yetkisi lazım.\n❌ 🇬🇧 You need `Administrator` permission.", ephemeral=True)

    @app_commands.command(name="coinflip", description="[TR] Yazı tura atar | [EN] Flip a coin!")
    async def coinflip(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 {interaction.user.mention}, bu komutu sadece **{COMMAND_CHANNEL_NAME}** kanalında kullanabilirsin!\n🇬🇧 {interaction.user.mention}, you can only use this in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        result = random.choice(["🇹🇷 Yazı | 🇬🇧 Heads <:coin:1363620713482817566>", "🇹🇷 Tura | 🇬🇧 Tails <:coin:1363620713482817566>"])
        await interaction.response.send_message(f"{interaction.user.mention} → {result}")

    @app_commands.command(name="dice", description="[TR] Zar atar | [EN] Rolls a dice (1-6).")
    async def dice(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 {interaction.user.mention}, bu komutu sadece **{COMMAND_CHANNEL_NAME}** kanalında kullanabilirsin!\n🇬🇧 {interaction.user.mention}, you can only use this in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        result = random.randint(1, 6)
        await interaction.response.send_message(f"{interaction.user.mention} → <:zar:1363622817014350075>\n🇹🇷 **{result}** attın!\n🇬🇧 You rolled a **{result}**!")

    @app_commands.command(name="slot", description="[TR] Slot makinesini çevir | [EN] Spin the slot machine!")
    async def slot(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 {interaction.user.mention}, bu komutu sadece **{COMMAND_CHANNEL_NAME}** kanalında kullanabilirsin!\n🇬🇧 {interaction.user.mention}, you can only use this in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        items = ["<:cherries:1363914253689422044>", "<:lemon:1363914245426905169>", "<:watermelon:1363914248392015922>", "<:grapes:1363914250606739746>", "<:SilverStar:1328066875170754713>", "<:diamond:1363914452344246334>"]
        s1, s2, s3 = random.choices(items, k=3)
        message = f"<:slot:1363620755161616677> | {s1} {s2} {s3}\n"
        if s1 == s2 == s3:
            message += f"<a:Para:1363908069305876681> {interaction.user.mention}\n🇹🇷 TEBRİKLER! Kazandın!\n🇬🇧 CONGRATULATIONS! You won!"
        else:
            message += f"<a:sob:1363908063647498343> {interaction.user.mention}\n🇹🇷 Kaybettin. Bir dahaki sefere!\n🇬🇧 You lost. Better luck next time!"
        await interaction.response.send_message(message)

    @app_commands.command(name="slap", description="[TR] Tokat atar | [EN] Slaps a user!")
    async def slap(self, interaction: discord.Interaction, user: discord.Member):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}** channel!", ephemeral=True)
        gifs = ["https://media.giphy.com/media/Gf3AUz3eBNbTW/giphy.gif", "https://media.giphy.com/media/Zau0yrl17uzdK/giphy.gif", "https://media.giphy.com/media/jLeyZWgtwgr2U/giphy.gif"]
        gif = random.choice(gifs)
        await interaction.response.send_message(f"🇹🇷 {interaction.user.mention}, {user.mention} kişisini tokatladı! <:ClownSkull:1312124365113921576>\n🇬🇧 {interaction.user.mention} slapped {user.mention}! <:ClownSkull:1312124365113921576>\n{gif}")

    @app_commands.command(name="hug", description="[TR] Sarılır | [EN] Hugs a user.")
    async def hug(self, interaction: discord.Interaction, user: discord.Member):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}** channel!", ephemeral=True)
        gifs = ["https://media.giphy.com/media/l2QDM9Jnim1YVILXa/giphy.gif", "https://media.giphy.com/media/sUIZWMnfd4Mb6/giphy.gif", "https://media.giphy.com/media/wnsgren9NtITS/giphy.gif"]
        gif = random.choice(gifs)
        await interaction.response.send_message(f"🇹🇷 {interaction.user.mention}, {user.mention} kişisine sarıldı! <:HeartClown:1306537753181163521>\n🇬🇧 {interaction.user.mention} hugged {user.mention}! <:HeartClown:1306537753181163521>\n{gif}")

    @app_commands.command(name="lovemeter", description="[TR] Aşk ölçer | [EN] Measures love percentage.")
    async def lovemeter(self, interaction: discord.Interaction, user: discord.Member):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}** channel!", ephemeral=True)
        percentage = random.randint(1, 100)
        await interaction.response.send_message(f"{interaction.user.mention} <a:Kalp:1363908074733047959> {user.mention}\n🇹🇷 Aşk yüzdesi: **%{percentage}**!\n🇬🇧 Love percentage: **{percentage}%**!")

    @app_commands.command(name="suggestanime", description="[TR] Anime önerir | [EN] Suggests a random anime.")
    async def suggestanime(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}** channel!", ephemeral=True)
        animes = ["Attack on Titan", "Death Note", "Naruto", "One Piece", "Jujutsu Kaisen", "Demon Slayer", "Steins;Gate"]
        selection = random.choice(animes)
        await interaction.response.send_message(f"{interaction.user.mention}\n🇹🇷 Sana şunu izlemeni öneririm: **{selection}**! <a:Dance:1306536369924870274>\n🇬🇧 I suggest you watch **{selection}**! <a:Dance:1306536369924870274>")

    @app_commands.command(name="mindquestion", description="[TR] Zihin açıcı soru | [EN] Mind-bending question.")
    async def mindquestion(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}** channel!", ephemeral=True)
        questions = [
            "🇹🇷 Zaman yolculuğu mümkün olsaydı, geçmişe mi yoksa geleceğe mi giderdin?\n🇬🇧 If time travel was possible, would you visit the past or the future?",
            "🇹🇷 Şu an rüya görmediğimizi nasıl bilebiliriz?\n🇬🇧 How do we know we're not dreaming right now?",
            "🇹🇷 Gerçeklik nedir?\n🇬🇧 What is reality?",
            "🇹🇷 Bir simülasyonda mı yaşıyoruz?\n🇬🇧 Are we living in a simulation?",
            "🇹🇷 Işık hızında giden bir arabanın farları çalışır mı?\n🇬🇧 If a car travels at the speed of light, do its headlights work?"
        ]
        await interaction.response.send_message(f"{interaction.user.mention} <:ClownCowboy:1306537774513524736>\n\n{random.choice(questions)}")

    @app_commands.command(name="serverinfo", description="[TR] Sunucu bilgisi | [EN] Server information.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("🇹🇷 Sadece sunucularda! | 🇬🇧 Only in servers.", ephemeral=True)
        embed = discord.Embed(title="🌐 Server Information / Sunucu Bilgisi", color=discord.Color.blue())
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.add_field(name="🇹🇷 İsim / 🇬🇧 Name", value=guild.name, inline=True)
        embed.add_field(name="🇹🇷 ID / 🇬🇧 ID", value=guild.id, inline=True)
        embed.add_field(name="🇹🇷 Kurucu / 🇬🇧 Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.add_field(name="🇹🇷 Üye Sayısı / 🇬🇧 Members", value=guild.member_count, inline=True)
        embed.add_field(name="🇹🇷 Kanal Sayısı / 🇬🇧 Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="🇹🇷 Rol Sayısı / 🇬🇧 Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="🇹🇷 Kuruluş Tarihi / 🇬🇧 Created On", value=discord.utils.format_dt(guild.created_at, style="F"), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="profile", description="[TR] Profil bilgisi | [EN] Profile information.")
    async def profile(self, interaction: discord.Interaction, user: discord.Member = None):
        target_user = user or interaction.user
        guild = interaction.guild

        embed = discord.Embed(
            title=f"👤 {target_user.display_name} - Profile / Profil",
            color=(target_user.color if target_user.color != discord.Color.default() else discord.Color.blurple())
        )
        embed.set_thumbnail(url=target_user.display_avatar.url)

        embed.add_field(
            name="🇹🇷 Kullanıcı / 🇬🇧 User",
            value=(f"{target_user.name}#{target_user.discriminator}" if target_user.discriminator != "0" else target_user.name),
            inline=True
        )
        embed.add_field(name="🇹🇷 ID / 🇬🇧 ID", value=target_user.id, inline=True)
        embed.add_field(name="🇹🇷 Durum / 🇬🇧 Status", value=str(target_user.status).capitalize(), inline=True)

        roles = [role.mention for role in reversed(target_user.roles) if role.is_default() is False]
        role_str = ", ".join(roles) if roles else "None / Yok"
        if len(role_str) > 1024: role_str = f"{len(roles)} roles / roller"

        embed.add_field(name=f"🇹🇷 Roller / 🇬🇧 Roles [{len(roles)}]", value=role_str, inline=False)
        embed.add_field(name="🇹🇷 Hesap Açılış / 🇬🇧 Acc. Created", value=discord.utils.format_dt(target_user.created_at, style="R"), inline=True)
        if guild and target_user.joined_at:
            embed.add_field(name="🇹🇷 Katılım / 🇬🇧 Joined Server", value=discord.utils.format_dt(target_user.joined_at, style="R"), inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverstats", description="[TR] Sunucu istatistikleri | [EN] Server statistics.")
    async def serverstats(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("🇹🇷 Sadece sunucularda! | 🇬🇧 Only in servers.", ephemeral=True)

        online_members = sum(1 for member in guild.members if member.status != discord.Status.offline)
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)

        embed = discord.Embed(title=f"📊 {guild.name} - Stats / İstatistikler", color=discord.Color.green())
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        embed.add_field(name="🇹🇷 Toplam Üye / 🇬🇧 Total Members", value=guild.member_count, inline=True)
        embed.add_field(name="🇹🇷 Çevrimiçi / 🇬🇧 Online", value=online_members, inline=True)
        embed.add_field(name="🇹🇷 Bot Sayısı / 🇬🇧 Bot Count", value=sum(1 for member in guild.members if member.bot), inline=True)
        embed.add_field(name="🇹🇷 Metin K. / 🇬🇧 Text Ch.", value=text_channels, inline=True)
        embed.add_field(name="🇹🇷 Ses K. / 🇬🇧 Voice Ch.", value=voice_channels, inline=True)
        embed.add_field(name="🇹🇷 Roller / 🇬🇧 Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="🇹🇷 Doğrulama / 🇬🇧 Verification", value=str(guild.verification_level).capitalize(), inline=True)
        embed.add_field(name="🇹🇷 Boost S. / 🇬🇧 Boost Level", value=f"Tier {guild.premium_tier} ({guild.premium_subscription_count} boosts)", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="guessnumber", description="[TR] Sayı tahmin oyunu | [EN] Number guessing game.")
    @app_commands.describe(guess="[TR] 1-100 arası | [EN] 1-100 guess")
    async def guessnumber(self, interaction: discord.Interaction, guess: app_commands.Range[int, 1, 100]):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}** channel!", ephemeral=True)
        
        user_id = interaction.user.id
        if user_id not in self.number_guess_games:
            number = random.randint(1, 100)
            self.number_guess_games[user_id] = number
            await interaction.response.send_message(f"🇹🇷 1-100 arası bir sayı tuttum. İlk tahminin {guess}.\n🇬🇧 I picked a number between 1-100. First guess is {guess}.")
            if guess == number:
                await interaction.followup.send("🇹🇷 Vay canına! İlk denemede bildin! 🎉\n🇬🇧 Wow! You got it on your first try! 🎉")
                del self.number_guess_games[user_id]
            elif guess < number:
                await interaction.followup.send("🇹🇷 Daha **büyük** bir sayı söyle.\n🇬🇧 Guess a **higher** number.")
            else:
                await interaction.followup.send("🇹🇷 Daha **küçük** bir sayı söyle.\n🇬🇧 Guess a **lower** number.")
        else:
            number = self.number_guess_games[user_id]
            if guess == number:
                await interaction.response.send_message(f"🇹🇷 Tebrikler! **{number}** sayısını doğru bildin! 🎉\n🇬🇧 Congratulations! You guessed **{number}** correctly! 🎉")
                del self.number_guess_games[user_id]
            elif guess < number:
                await interaction.response.send_message(f"🇹🇷 Tahminin ({guess}) çok küçük. Daha **büyük** bir sayı söyle.\n🇬🇧 Your guess ({guess}) is too low. Guess **higher**.")
            else:
                await interaction.response.send_message(f"🇹🇷 Tahminin ({guess}) çok büyük. Daha **küçük** bir sayı söyle.\n🇬🇧 Your guess ({guess}) is too high. Guess **lower**.")

    @app_commands.command(name="wordgame", description="[TR] Kelime bulma oyunu | [EN] Unscramble the word.")
    async def wordgame(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}** channel!", ephemeral=True)
        
        words = ["apple", "table", "pencil", "notebook", "computer", "discord", "python", "programming", "game", "giveaway"]
        word = random.choice(words)
        scrambled_list = list(word)
        random.shuffle(scrambled_list)
        scrambled = "".join(scrambled_list)

        while scrambled == word:
            random.shuffle(scrambled_list)
            scrambled = "".join(scrambled_list)

        await interaction.response.send_message(f"🇹🇷 Bu harfleri düzelterek İngilizce kelimeyi bul: `{scrambled}` (30 saniyen var!)\n🇬🇧 Unscramble these letters to find the English word: `{scrambled}` (You have 30s!)")

        def check(m: discord.Message):
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id

        try:
            answer_msg = await self.bot.wait_for("message", check=check, timeout=30.0)
            if answer_msg.content.lower() == word:
                await interaction.followup.send(f"🇹🇷 Tebrikler {interaction.user.mention}! Kelime şuydu: **{word}** <:partying_face:1364019186619121665>\n🇬🇧 Congrats! The word was: **{word}**")
            else:
                await interaction.followup.send(f"🇹🇷 Yanlış cevap {interaction.user.mention}. Doğru kelime: **{word}** <:pensive:1364019186619121666>\n🇬🇧 Wrong answer. The correct word was: **{word}**")
        except asyncio.TimeoutError:
            await interaction.followup.send(f"🇹🇷 Süre doldu {interaction.user.mention}! Doğru kelime: **{word}** <:hourglass_flowing_sand:1364019186619121667>\n🇬🇧 Time's up! The correct word was: **{word}**")

    @app_commands.command(name="ping", description="[TR] Bot gecikmesini gösterir | [EN] Shows bot's latency.")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(title="Pong! <:ping_pong:1364019186619121668>", description=f"🇹🇷 Gecikme / 🇬🇧 Latency: **{latency}ms**", color=discord.Color.random())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="[TR] Komut listesi | [EN] Displays the bot commands.")
    async def help_cmd(self, interaction: discord.Interaction):
        cmd_list = [
            f"`/coinflip`: 🇹🇷 Yazı tura / 🇬🇧 Flips a coin. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/dice`: 🇹🇷 Zar atar / 🇬🇧 Rolls a 1-6 dice. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/slot`: 🇹🇷 Slot çevirir / 🇬🇧 Spins the slot machine. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/slap <user>`: 🇹🇷 Tokat atar / 🇬🇧 Slaps a member. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/hug <user>`: 🇹🇷 Sarılır / 🇬🇧 Hugs a member. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/lovemeter <user>`: 🇹🇷 Aşk ölçer / 🇬🇧 Measures love. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/suggestanime`: 🇹🇷 Anime önerir / 🇬🇧 Suggests an anime. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/mindquestion`: 🇹🇷 Zeka sorusu / 🇬🇧 Mind question. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/guessnumber <guess>`: 🇹🇷 Sayı tahmini / 🇬🇧 Number guess. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/wordgame`: 🇹🇷 Kelime oyunu / 🇬🇧 Word game. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/rps <choice>`: 🇹🇷 Taş kağıt makas / 🇬🇧 Play RPS. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/cupgame`: 🇹🇷 Bardak oyunu / 🇬🇧 Cup game. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/fish`: 🇹🇷 Balık tutma / 🇬🇧 Fish game. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/quickdecision`: 🇹🇷 Hızlı karar / 🇬🇧 Quick decision. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/robloxprofile <username>`: 🇹🇷 RBX Profil / 🇬🇧 RBX Profile. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/robloxitem <item_name>`: 🇹🇷 RBX Eşya / 🇬🇧 RBX Item. (`{COMMAND_CHANNEL_NAME}`)",
            "`/ping`: 🇹🇷 Gecikme süresi / 🇬🇧 Bot latency.",
            "`/serverinfo`: 🇹🇷 Sunucu bilgisi / 🇬🇧 Server info.",
            "`/profile [user]`: 🇹🇷 Profil bilgisi / 🇬🇧 Profile info.",
            "`/serverstats`: 🇹🇷 Sunucu istatistikleri / 🇬🇧 Server stats.",
            f"`/leaderboard`: 🇹🇷 Liderlik tablosu / 🇬🇧 Leaderboard. (`{COMMAND_CHANNEL_NAME}`)",
            f"`/giveaway-start ...`: 🇹🇷 Çekiliş başlatır / 🇬🇧 Starts giveaway. (`{GIVEAWAY_CHANNEL_NAME}`)",
            f"`/giveaway-end ...`: 🇹🇷 Çekilişi bitirir / 🇬🇧 Ends giveaway early. (`{GIVEAWAY_CHANNEL_NAME}`)",
            f"`/giveaway-draw ...`: 🇹🇷 Manuel Çekiliş / 🇬🇧 Manual Giveaway draw. (`{GIVEAWAY_CHANNEL_NAME}`)",
            "`/voice ...`: 🇹🇷 Özel Oda komutları / 🇬🇧 Temp Room Commands.",
            "`/clear <amount>`: 🇹🇷 Mesaj siler / 🇬🇧 Deletes messages.",
            "`/messageinfo <user>`: 🇹🇷 Mesaj sayısı / 🇬🇧 Message count.",
            "`/massrole <role>`: 🇹🇷 Toplu rol verme / 🇬🇧 Mass role grant.",
            "`/resetnames`: 🇹🇷 İsimleri sıfırlar / 🇬🇧 Reset nicknames.",
            "`/help`: 🇹🇷 Yardım menüsü / 🇬🇧 Help menu."
        ]
        
        embed = discord.Embed(
            title="📜 Help Menu / Yardım Menüsü",
            description=f"🇹🇷 Merhaba {interaction.user.mention}! Komutlar:\n🇬🇧 Hello! Here are the commands:",
            color=discord.Color.blue()
        )

        fun_games = [c for c in cmd_list if f"`{COMMAND_CHANNEL_NAME}`" in c and "/leaderboard" not in c and "roblox" not in c]
        roblox_cmds = [c for c in cmd_list if "roblox" in c]
        info_tools = [
            c for c in cmd_list 
            if f"`{COMMAND_CHANNEL_NAME}`" not in c and "giveaway" not in c and "clear" not in c 
            and "resetnames" not in c and "help" not in c and "messageinfo" not in c 
            and "massrole" not in c and "/voice" not in c
        ]
        info_tools.append(next(c for c in cmd_list if "/leaderboard" in c))
        giveaway = [c for c in cmd_list if "giveaway" in c]
        voice_cmds = [c for c in cmd_list if "/voice" in c]
        mod_settings = [c for c in cmd_list if "clear" in c or "resetnames" in c or "messageinfo" in c or "massrole" in c]
        other = [c for c in cmd_list if "help" in c]

        embed.add_field(name=f"🎮 Eğlence & Oyunlar / Fun & Games ({COMMAND_CHANNEL_NAME})", value="\n".join(fun_games), inline=False)
        embed.add_field(name=f"🟥 Roblox ({COMMAND_CHANNEL_NAME})", value="\n".join(roblox_cmds), inline=False)
        embed.add_field(name="ℹ️ Bilgi & Araçlar / Info & Tools", value="\n".join(info_tools), inline=False)
        embed.add_field(name=f"🎁 Çekiliş / Giveaway ({GIVEAWAY_CHANNEL_NAME})", value="\n".join(giveaway), inline=False)
        embed.add_field(name="🔊 Özel Oda / Temp Voice", value="\n".join(voice_cmds), inline=False)
        embed.add_field(name="🛡️ Moderasyon / Moderation", value="\n".join(mod_settings), inline=False)
        embed.add_field(name="⚙️ Diğer / Other", value="\n".join(other), inline=False)

        embed.set_footer(text="TR: <> zorunlu, [] isteğe bağlı | EN: <> required, [] optional")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="[TR] Liderlik tablosu | [EN] Shows the most active members.")
    @app_commands.checks.cooldown(1, 10, key=lambda i: (i.guild_id, i.user.id))
    async def leaderboard(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}** channel!", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("🇹🇷 Sadece sunucularda! | 🇬🇧 Only in servers.", ephemeral=True)

        guild_id = interaction.guild.id
        top_limit = 10
        save_data()

        guild_message_counts = user_message_counts.get(guild_id, {})
        sorted_messages = sorted(guild_message_counts.items(), key=lambda item: item[1], reverse=True)

        message_lb_text = ""
        rank = 1
        for user_id, count in sorted_messages[:top_limit]:
            member = interaction.guild.get_member(user_id)
            if member:
                message_lb_text += f"{rank}. {member.mention}: **{count}** messages\n"
                rank += 1
            else:
                try:
                    user = await self.bot.fetch_user(user_id)
                    message_lb_text += f"{rank}. Past Member/Eski Üye ({user.name}): **{count}** messages\n"
                    rank += 1
                except Exception:
                    pass

        if not message_lb_text: message_lb_text = "Yok / No data."

        guild_voice_time = user_voice_time.get(guild_id, {})
        sorted_voice = sorted(guild_voice_time.items(), key=lambda item: item[1], reverse=True)

        def format_duration(total_seconds):
            if total_seconds <= 0: return "0 s"
            total_seconds = int(total_seconds)
            days, remainder = divmod(total_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            parts = []
            if days > 0: parts.append(f"{days}d/g")
            if hours > 0: parts.append(f"{hours}h/s")
            if minutes > 0: parts.append(f"{minutes}m/d")
            if seconds > 0 or not parts: parts.append(f"{seconds}s")
            return " ".join(parts)

        voice_lb_text = ""
        rank = 1
        for user_id, total_seconds in sorted_voice[:top_limit]:
            member = interaction.guild.get_member(user_id)
            if member:
                voice_lb_text += f"{rank}. {member.mention}: **{format_duration(total_seconds)}**\n"
                rank += 1
            else:
                try:
                    user = await self.bot.fetch_user(user_id)
                    voice_lb_text += f"{rank}. Past Member/Eski Üye ({user.name}): **{format_duration(total_seconds)}**\n"
                    rank += 1
                except Exception:
                    pass

        if not voice_lb_text: voice_lb_text = "Yok / No data."

        embed = discord.Embed(title=f"🏆 {interaction.guild.name} - Leaderboard / Liderlik", color=discord.Color.gold())
        embed.add_field(name="💬 🇹🇷 En Çok Mesaj Yazanlar\n🇬🇧 Top Messagers", value=message_lb_text, inline=False)
        embed.add_field(name="🔊 🇹🇷 En Çok Seste Duranlar\n🇬🇧 Top Voice Activity", value=voice_lb_text, inline=False)
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="Auto-saved / Otomatik kaydedilir")
        
        await interaction.response.send_message(embed=embed)

    @leaderboard.error
    async def leaderboard_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f"⏳ 🇹🇷 Bekle: {error.retry_after:.1f}s | 🇬🇧 Wait: {error.retry_after:.1f}s", ephemeral=True)

    @app_commands.command(name="messageinfo", description="[TR] Kullanıcının mesaj sayısı | [EN] User's message count.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def messageinfo(self, interaction: discord.Interaction, user: discord.Member):
        guild_id = interaction.guild.id
        msg_count = user_message_counts.get(guild_id, {}).get(user.id, 0)
        embed = discord.Embed(title="📊 Mesaj İstatistiği / Message Stats", color=discord.Color.blue())
        embed.description = f"🇹🇷 {user.mention} bu sunucuda toplam **{msg_count}** mesaj attı.\n🇬🇧 {user.mention} has sent a total of **{msg_count}** messages here."
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @messageinfo.error
    async def messageinfo_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("🇹🇷 'Mesajları Yönet' izni lazım. | 🇬🇧 Need 'Manage Messages'.", ephemeral=True)

    @app_commands.command(name="massrole", description="[TR] Herkese rol verir | [EN] Gives role to EVERYONE.")
    @app_commands.checks.has_permissions(administrator=True)
    async def massrole(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.send_message(f"⏳ 🇹🇷 Herkese **{role.name}** rolü veriliyor. Bekleyin...\n⏳ 🇬🇧 Giving **{role.name}** to everyone. Please wait...")
        given_count = 0
        for member in interaction.guild.members:
            if not member.bot and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Mass role command executed.")
                    given_count += 1
                    await asyncio.sleep(0.5)
                except discord.Forbidden:
                    return await interaction.followup.send("❌ 🇹🇷 Hata: Botun rol verme yetkisi/sırası yetersiz.\n❌ 🇬🇧 Error: Bot lacks permission/hierarchy for this role.")
                except Exception as e:
                    print(f"Mass role error: {e}")
        await interaction.followup.send(f"✅ 🇹🇷 İşlem Tamam! **{given_count}** kişiye {role.mention} verildi.\n✅ 🇬🇧 Process Completed! Granted to **{given_count}** members.")

    @massrole.error
    async def massrole_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("🇹🇷 `Yönetici` izni lazım. | 🇬🇧 Need `Administrator`.", ephemeral=True)

    @app_commands.command(name="clear", description="[TR] Mesajları siler | [EN] Deletes messages.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], user: discord.Member = None):
        if not interaction.channel or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("🇹🇷 Sadece metin kanalları! | 🇬🇧 Text channels only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            if user:
                def check(m): return m.author == user
                deleted_msgs = await interaction.channel.purge(limit=amount, check=check, before=interaction.created_at)
                await interaction.followup.send(f"🇹🇷 {user.mention} kullanıcısının {len(deleted_msgs)} mesajı silindi.\n🇬🇧 Deleted {len(deleted_msgs)} messages from {user.mention}.", ephemeral=True)
            else:
                deleted_msgs = await interaction.channel.purge(limit=amount, before=interaction.created_at)
                await interaction.followup.send(f"🇹🇷 Son {len(deleted_msgs)} mesaj silindi.\n🇬🇧 Deleted the last {len(deleted_msgs)} messages.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("🇹🇷 Yeterli yetkim yok! | 🇬🇧 Not enough permissions!", ephemeral=True)

    @clear.error
    async def clear_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("🇹🇷 'Mesajları Yönet' izni lazım. | 🇬🇧 Need 'Manage Messages'.", ephemeral=True)

    @app_commands.command(name="rps", description="[TR] Taş-Kağıt-Makas | [EN] Rock-Paper-Scissors.")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Taş / Rock 🗿", value="rock"),
        app_commands.Choice(name="Kağıt / Paper 📄", value="paper"),
        app_commands.Choice(name="Makas / Scissors ✂️", value="scissors"),
    ])
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        user_val = choice.value
        user_name = choice.name
        bot_choices = {"rock": "Taş/Rock 🗿", "paper": "Kağıt/Paper 📄", "scissors": "Makas/Scissors ✂️"}
        bot_val = random.choice(list(bot_choices.keys()))
        bot_name = bot_choices[bot_val]
        result = ""
        if user_val == bot_val: result = "🇹🇷 Berabere! 🤔\n🇬🇧 It's a tie! 🤔"
        elif (user_val == "rock" and bot_val == "scissors") or (user_val == "paper" and bot_val == "rock") or (user_val == "scissors" and bot_val == "paper"):
            result = "🇹🇷 Tebrikler, Kazandın! 🎉\n🇬🇧 Congrats, you won! 🎉"
        else:
            result = "🇹🇷 Kaybettin! Ben kazandım. <:PepeLaugh:1306537851710345216>\n🇬🇧 You lost! I win. <:PepeLaugh:1306537851710345216>"
        await interaction.response.send_message(f"{interaction.user.mention}:\n🇹🇷 Senin seçimin / 🇬🇧 Your choice: **{user_name}**\n🇹🇷 Benim seçimim / 🇬🇧 My choice: **{bot_name}**\n\n{result}")

    @app_commands.command(name="cupgame", description="[TR] 3 Bardak oyunu | [EN] 3-Cup hidden object game.")
    async def cupgame(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        cups = ["🥛", "🥛", "🥛"]
        hidden_object = "💎"
        correct_pos = random.randint(0, 2)
        await interaction.response.send_message(f"{interaction.user.mention}\n🇹🇷 Obje ({hidden_object}) hangi bardağın altında? (Tepki ver)\n🇬🇧 Which cup hides the object ({hidden_object})? (React)\n{' '.join(cups)}")
        msg = await interaction.original_response()
        reactions = ["1️⃣", "2️⃣", "3️⃣"]
        for r in reactions:
            try: await msg.add_reaction(r)
            except Exception: return await interaction.followup.send("Hata / Error.", ephemeral=True)
        def check(reaction, user):
            return user.id == interaction.user.id and str(reaction.emoji) in reactions and reaction.message.id == msg.id
        try:
            reaction, user = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
            selected_pos = reactions.index(str(reaction.emoji))
            result_cups = ["🥛", "🥛", "🥛"]
            if selected_pos == correct_pos:
                result_cups[correct_pos] = f"**{hidden_object}**"
            else:
                result_cups[correct_pos] = f"**{hidden_object}**"
                result_cups[selected_pos] = "❌"
            result_message = f"{user.mention}, Seçimin / Selected: {reaction.emoji}\n{' '.join(result_cups)}\n"
            if selected_pos == correct_pos: result_message += "🇹🇷 Tebrikler! Buldun ve kazandın! 🎉\n🇬🇧 Congrats! You found it and won! 🎉"
            else: result_message += "🇹🇷 Maalesef yanlış bardak! Kaybettin. <:pensive:1364019186619121666>\n🇬🇧 Wrong cup! You lost. <:pensive:1364019186619121666>"
            await interaction.edit_original_response(content=result_message, view=None)
        except asyncio.TimeoutError:
            result_cups = ["🥛", "🥛", "🥛"]
            result_cups[correct_pos] = f"**{hidden_object}**"
            timeout_msg = f"{interaction.user.mention}, 🇹🇷 Süre doldu! ⏳ Obje buradaydı:\n🇬🇧 Time's up! ⏳ The object was here:\n{' '.join(result_cups)}"
            try: await interaction.edit_original_response(content=timeout_msg, view=None)
            except Exception: pass

    @app_commands.command(name="fish", description="[TR] Balık tut | [EN] Catch some fish.")
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.user.id)
    async def fish(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        catches = [
            ("Sıradan Balık / Common Fish", "🐟", 40),
            ("Levrek / Bass", "🐠", 25),
            ("Somon / Salmon", "🍣", 15),
            ("Eski Bot / Old Boot", "🥾", 10),
            ("Yosun / Seaweed", "🌿", 5),
            ("Nadir Balık / Rare Fish", "🐡", 4),
            ("Efsanevi / Legendary Fish", "🐠", 0.9),
            ("Hazine / Sunken Treasure", "💰", 0.1),
        ]
        names, emojis, weights = zip(*catches)
        caught = random.choices(catches, weights=weights, k=1)[0]
        name, emoji, _ = caught
        embed = discord.Embed(title="🎣 Fishing / Balık Tutma", description=f"{interaction.user.mention}\n🇹🇷 Oltanı attın ve...\n🇬🇧 You cast your line and...", color=discord.Color.blue())
        embed.add_field(name="Yakalanan / You Caught:", value=f"{emoji} **{name}**", inline=False)
        if "Legendary" in name or "Treasure" in name:
            embed.color = discord.Color.gold()
            embed.add_field(name="Wow!", value="🇹🇷 Çok nadir bir şey yakaladın!\n🇬🇧 You caught something very rare!", inline=False)
        elif "Boot" in name or "Seaweed" in name:
            embed.color = discord.Color.dark_grey()
            embed.add_field(name="Too bad / Kötü Şans", value="🇹🇷 Biraz şanssızdın...\n🇬🇧 You had a bit of bad luck...", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quickdecision", description="[TR] Hızlı karar oyunu | [EN] Quick decision game.")
    @app_commands.checks.cooldown(1, 15, key=lambda i: i.user.id)
    async def quickdecision(self, interaction: discord.Interaction):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        scenarios = [
            {
                "tr": "Önünde aniden bir sandık belirdi!", "en": "A chest suddenly appears in front of you!",
                "options": {"🔑": "Aç/Open", "💥": "Kır/Smash", "🚶‍♀️": "Geç/Walk away"},
                "outcomes": {
                    "🔑": "🇹🇷 Sandığı açtın ve parlak bir eşya buldun! ✨\n🇬🇧 You opened the chest and found a glowing item! ✨",
                    "💥": "🇹🇷 Kırdın ama içinden sadece toz çıktı. 💨\n🇬🇧 You smashed it but only dust came out. 💨",
                    "🚶‍♀️": "🇹🇷 Merakına yenilmedin ve yürüdün.\n🇬🇧 You didn't give in to curiosity and kept walking."
                }
            },
            {
                "tr": "Yerde parlayan bir bozuk para var.", "en": "You see a shiny coin on the ground.",
                "options": {"💰": "Al/Pick it up", "👟": "Bas/Step on it", "👀": "Bak/Look"},
                "outcomes": {
                    "💰": "🇹🇷 Parayı aldın! Belki işe yarar. 💰\n🇬🇧 You picked it up! Maybe it'll be useful. 💰",
                    "👟": "🇹🇷 Üstüne bastın ve toza dönüştü...\n🇬🇧 You stepped on it and it turned to dust...",
                    "👀": "🇹🇷 Sadece baktın ve para orada kaldı.\n🇬🇧 You just looked at it and it stayed there."
                }
            }
        ]
        scenario = random.choice(scenarios)
        options, outcomes = scenario["options"], scenario["outcomes"]
        option_emojis = list(options.keys())
        embed = discord.Embed(title="⚡ Hızlı Karar / Quick Decision ⚡", description=f"🇹🇷 {scenario['tr']}\n🇬🇧 {scenario['en']}", color=discord.Color.orange())
        embed.add_field(name="Seçenekler / Options:", value="\n".join([f"{emoji} {desc}" for emoji, desc in options.items()]), inline=False)
        embed.set_footer(text="10 saniyen var! / 10 seconds limit!")
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        for emoji in option_emojis:
            try: await msg.add_reaction(emoji)
            except Exception: return await interaction.followup.send("Hata / Error.", ephemeral=True)
        def check(reaction, user):
            return user.id == interaction.user.id and reaction.message.id == msg.id and str(reaction.emoji) in option_emojis
        try:
            reaction, user = await self.bot.wait_for("reaction_add", timeout=10.0, check=check)
            selected_emoji = str(reaction.emoji)
            outcome_text = outcomes.get(selected_emoji, "")
            await interaction.followup.send(f"{user.mention}, Seçimin / Selected: {selected_emoji}\n\n{outcome_text}")
            try: await msg.clear_reactions()
            except Exception: pass
        except asyncio.TimeoutError:
            await interaction.followup.send(f"{interaction.user.mention}, 🇹🇷 Çok yavaştın! Süre doldu. ⏳\n🇬🇧 You were too slow! Time's up. ⏳")

    @app_commands.command(name="robloxprofile", description="[TR] Roblox profilini gösterir | [EN] Shows Roblox profile.")
    @app_commands.describe(username="[TR] Kullanıcı adı [EN] Username")
    async def robloxprofile(self, interaction: discord.Interaction, username: str):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        await interaction.response.defer(ephemeral=False)
        embed = discord.Embed(title=f"Roblox User: {username}", color=discord.Color.red())
        embed.description = "🔍 🇹🇷 Yakında eklenecek: API üzerinden otomatik profil verisi.\n🇬🇧 Coming soon: Automatic profile data from API."
        embed.add_field(name="Aranan / Searched", value=f"**{username}**", inline=False)
        embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Roblox_player_icon_black.svg/1200px-Roblox_player_icon_black.svg.png")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="robloxitem", description="[TR] Roblox eşyası arar | [EN] Searches a Roblox item.")
    @app_commands.describe(item_name="[TR] Eşya adı [EN] Item name")
    async def robloxitem(self, interaction: discord.Interaction, item_name: str):
        if interaction.channel.name != COMMAND_CHANNEL_NAME:
            return await interaction.response.send_message(f"🇹🇷 Sadece **{COMMAND_CHANNEL_NAME}** kanalında!\n🇬🇧 Only in **{COMMAND_CHANNEL_NAME}**!", ephemeral=True)
        await interaction.response.defer(ephemeral=False)
        embed = discord.Embed(title=f"Roblox Item: {item_name}", color=discord.Color.dark_theme())
        embed.description = "🎨 🇹🇷 Yakında eklenecek: Katalogtaki UGC eşyaları görüntüleme.\n🇬🇧 Coming soon: View UGC items from the catalog."
        embed.add_field(name="Aranan / Searched", value=f"**{item_name}**", inline=False)
        await interaction.followup.send(embed=embed)


# --- Background Tasks ---
@tasks.loop(minutes=3)
async def auto_save():
    save_data()


# --- Events ---
@bot.event
async def on_ready():
    print(f"Logged in as / Giriş yapıldı: {bot.user}! ID: {bot.user.id}")
    load_data()
    auto_save.start()
    try:
        await bot.change_presence(activity=discord.Game(name="§ | /help Cr:Sanby (beta)"))
    except Exception:
        pass

    try:
        await bot.tree.sync()
        print("Slash komutları senkronize edildi.")
    except Exception as e:
        print(f"Command sync error / Komut senk hatası: {e}")

    for guild in bot.guilds:
        if guild.id not in user_message_counts: user_message_counts[guild.id] = {}
        if guild.id not in user_voice_time: user_voice_time[guild.id] = {}
        if guild.id not in user_voice_start_time: user_voice_start_time[guild.id] = {}
        try:
            invites = await guild.invites()
            invite_cache[guild.id] = {invite.code: invite.uses for invite in invites}
        except Exception:
            invite_cache[guild.id] = {}

@bot.event
async def on_member_join(member: discord.Member):
    await bot.wait_until_ready()
    guild = member.guild
    if guild.id not in user_message_counts: user_message_counts[guild.id] = {}
    if guild.id not in user_voice_time: user_voice_time[guild.id] = {}
    if guild.id not in user_voice_start_time: user_voice_start_time[guild.id] = {}

    role_name = "§ ~ M"
    role = discord.utils.get(guild.roles, name=role_name)
    if role:
        try: await member.add_roles(role, reason="New member join.")
        except Exception: pass

    join_leave_channel_name = "§🚪join-leave"
    join_leave_channel = discord.utils.get(guild.text_channels, name=join_leave_channel_name)
    if not join_leave_channel: return

    inviter = None
    invite_used = None
    inviter_invite_count = 0
    try:
        old_invites_uses = invite_cache.get(guild.id, {})
        new_invites = await guild.invites()
        current_invites_uses = {invite.code: invite.uses for invite in new_invites}
        for code, new_uses in current_invites_uses.items():
            old_uses = old_invites_uses.get(code, 0)
            if new_uses > old_uses:
                invite_used = next((inv for inv in new_invites if inv.code == code), None)
                if invite_used and invite_used.inviter:
                    inviter = invite_used.inviter
                    inviter_invite_count = sum(i.uses for i in new_invites if i.inviter == inviter)
                break
        invite_cache[guild.id] = current_invites_uses
    except Exception: pass

    msg = f"<a:Invite:1361358899441172520> 🇹🇷 Merhaba {member.mention}, **{guild.name}** sunucusuna hoş geldin!\n🇬🇧 Hello {member.mention}, Welcome to **{guild.name}**!\n\n"
    msg += f"<a:ok:1363561678222000248> 🇹🇷 Artık **{guild.member_count}** kişiyiz!!\n🇬🇧 We are now **{guild.member_count}** members!!\n"
    if inviter: msg += f"<:Invite1:1363567960416977026> 🇹🇷 Davet eden / 🇬🇧 Invited by: {inviter.mention} <a:ye:1361358920127479949> (Total/Toplam: **{inviter_invite_count}**)"
    elif invite_used: msg += f"🇹🇷 Kod / 🇬🇧 Code '{invite_used.code}'. 🇹🇷 Davet eden bulunamadı / 🇬🇧 Inviter not found. <:hmm:1364019186619121664>"
    else: msg += "🇹🇷 Davet eden bulunamadı / 🇬🇧 Inviter not found. <:hmm:1364019186619121664>"

    embed = discord.Embed(description=msg, color=discord.Color.green())
    embed.set_author(name=f"{member.name} Joined! / Katıldı!", icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    try: await join_leave_channel.send(embed=embed)
    except Exception: pass

@bot.event
async def on_member_remove(member: discord.Member):
    await bot.wait_until_ready()
    guild = member.guild
    join_leave_channel_name = "§🚪join-leave"
    channel = discord.utils.get(guild.text_channels, name=join_leave_channel_name)

    if channel:
        msg = f"<a:Exit:1363560739423387709> 🇹🇷 Güle güle **{member.mention}**. Seni özleyeceğiz.\n🇬🇧 Goodbye **{member.mention}**. We will miss you.\n\n<a:ok:1363561678222000248> 🇹🇷 **{member.guild.member_count}** kişi kaldık.\n🇬🇧 There are **{member.guild.member_count}** members left."
        embed = discord.Embed(description=msg, color=discord.Color.red())
        embed.set_author(name=f"{member.name} Left. / Ayrıldı.", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        try: await channel.send(embed=embed)
        except Exception: pass

    guild_id = guild.id
    user_id = member.id
    if guild_id in user_voice_start_time and user_id in user_voice_start_time[guild_id]:
        try:
            start_time = user_voice_start_time[guild_id].pop(user_id)
            duration = time.time() - start_time
            if duration > 0: user_voice_time[guild_id][user_id] = user_voice_time[guild_id].get(user_id, 0) + duration
        except Exception: pass

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None or message.webhook_id is not None:
        return

    guild_id = message.guild.id
    user_id = message.author.id
    channel = message.channel

    if guild_id not in user_message_counts: user_message_counts[guild_id] = {}
    user_message_counts[guild_id][user_id] = user_message_counts[guild_id].get(user_id, 0) + 1

    # --- SPAM PROTECTION ---
    if not message.author.guild_permissions.manage_messages:
        now = datetime.now()
        if user_id not in user_message_history:
            user_message_history[user_id] = {"messages": [], "last_timestamp": now}
        history = user_message_history[user_id]

        if now - history["last_timestamp"] > SPAM_TIMEFRAME:
            history["messages"] = [message.content.lower()]
        else:
            history["messages"].append(message.content.lower())
            history["messages"] = history["messages"][-SPAM_THRESHOLD:]

        history["last_timestamp"] = now
        if len(history["messages"]) == SPAM_THRESHOLD and len(set(history["messages"])) == 1:
            try:
                await message.author.timeout(MUTE_DURATION, reason="Repeated messaging (spam)")
                def is_spam_msg(m): return m.author == message.author and m.content.lower() == history["messages"][0]
                await channel.purge(limit=15, check=is_spam_msg)
                warning_msg = await channel.send(f"🚨 {message.author.mention}\n🇹🇷 Spam yaptığın için susturuldun ve mesajların silindi.\n🇬🇧 You have been timed out for spamming, and your messages were cleared.")
                await warning_msg.delete(delay=5)
                history["messages"] = []
            except Exception as e: print(f"Spam prevention error: {e}")

    # --- LINK AND GIF PROTECTION (EXCEPT TENOR) ---
    if not message.author.guild_permissions.administrator:
        msg_lower = message.content.lower()
        contains_link = "http://" in msg_lower or "https://" in msg_lower or "www." in msg_lower or "discord.gg/" in msg_lower
        is_allowed_gif = "tenor.com" in msg_lower

        if contains_link and not is_allowed_gif:
            try:
                await message.delete()
                link_warning = await channel.send(f"⚠️ {message.author.mention}\n🇹🇷 Burada sadece Tenor GIF'lerine izin verilir! Diğer linkler yasak.\n🇬🇧 Only Tenor GIFs are allowed here! Other links are prohibited.")
                await link_warning.delete(delay=5)
            except Exception: pass

    greetings = ["hi", "hello", "hey", "sup", "howdy", "greetings", "merhaba", "selam", "sa", "sea"]
    replies = [
        f"🇹🇷 Merhaba {message.author.mention}, hoş geldin!\n🇬🇧 Hello there {message.author.mention}, welcome!",
        f"🇹🇷 Selam {message.author.mention}!\n🇬🇧 Greetings {message.author.mention}!",
        f"🇹🇷 Selam {message.author.mention}, nasılsın?\n🇬🇧 Hi {message.author.mention}, how are you doing?",
        f"🇹🇷 Hey {message.author.mention}!\n🇬🇧 Hey {message.author.mention}!"
    ]
    msg_lower = message.content.lower().strip()
    if msg_lower in greetings:
        if random.random() < 0.6:
            try: await message.reply(random.choice(replies), mention_author=False)
            except Exception: pass

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot: return

    guild = member.guild
    guild_id = guild.id
    user_id = member.id

    if guild_id not in user_voice_time: user_voice_time[guild_id] = {}
    if guild_id not in user_voice_start_time: user_voice_start_time[guild_id] = {}

    def should_start_tracking(state: discord.VoiceState):
        return (state.channel is not None and state.channel != guild.afk_channel and not state.self_mute and not state.self_deaf and not state.mute and not state.deaf)

    was_tracking = user_id in user_voice_start_time.get(guild_id, {})
    is_tracking_now = should_start_tracking(after)

    if was_tracking and not is_tracking_now:
        try:
            start_time = user_voice_start_time[guild_id].pop(user_id)
            duration = time.time() - start_time
            if duration > 0: user_voice_time[guild_id][user_id] = user_voice_time[guild_id].get(user_id, 0) + duration
        except Exception: pass
    elif not was_tracking and is_tracking_now:
        user_voice_start_time[guild_id][user_id] = time.time()
    elif was_tracking and is_tracking_now and before.channel != after.channel:
        try:
            start_time = user_voice_start_time[guild_id].pop(user_id)
            duration = time.time() - start_time
            if duration > 0: user_voice_time[guild_id][user_id] = user_voice_time[guild_id].get(user_id, 0) + duration
            user_voice_start_time[guild_id][user_id] = time.time()
        except Exception: pass

    creator_vc_id = voice_system_data.get(str(guild_id))
    
    if after.channel and str(after.channel.id) == str(creator_vc_id):
        category = after.channel.category
        new_channel = await guild.create_voice_channel(
            name=f"{member.display_name}'ın Odası",
            category=category,
            user_limit=0
        )
        temp_voice_channels[str(new_channel.id)] = str(member.id)
        save_data()
        await member.move_to(new_channel)

    if before.channel and str(before.channel.id) in temp_voice_channels:
        if len(before.channel.members) == 0:
            del temp_voice_channels[str(before.channel.id)]
            save_data()
            try:
                await before.channel.delete()
            except Exception as e:
                print(f"Oda silinirken hata: {e}")

async def setup(bot_instance: commands.Bot):
    await bot_instance.add_cog(CommandsCog(bot_instance))
    print("Commands loaded / Komutlar yüklendi.")

async def main():
    
    bot.run(os.environ.get('DISCORD_TOKEN')) 

   

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        save_data()
        print("\nShutting down, data saved... / Kapatılıyor, veriler kaydedildi...")