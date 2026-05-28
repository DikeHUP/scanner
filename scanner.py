import asyncio
import csv
import os
import zipfile
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import FloodWaitError

# ==================== KONFIGÜRASYON ====================
API_ID = 31318870  # Kendi API ID'niz ile değiştirin
API_HASH = '7f5771aa235fbfbf66722f1b9516da45'  # Kendi API Hash'iniz ile değiştirin

# Rapor gönderilecek Telegram kullanıcı adı (@ ile)
YOUR_USER_ID = '@merhababendike'  # Kendi kullanıcı adınız ile değiştirin

# Tarama saatleri (günde 3 kez)
SCAN_HOURS = [0, 12, 18]  # 00:00, 12:00, 18:00

# Kayıt dizini
RECORDS_DIR = 'user_records'

# Her taramada okunacak mesaj sayısı
MESSAGE_LIMIT = 2500
# =======================================================

class GroupUserScanner:
    def __init__(self):
        self.client = TelegramClient('user_scanner', API_ID, API_HASH)
        self.recorded_users = {}  # {group_folder: set(user_ids)}
        self.last_scan_dates = {}  # Son tarama tarihlerini tut
        self.error_reported = False  # Hata raporu gönderildi mi?
        
    def load_records(self):
        """Daha önce kaydedilmiş kullanıcıları yükler"""
        if not os.path.exists(RECORDS_DIR):
            os.makedirs(RECORDS_DIR)
            
        for group_folder in os.listdir(RECORDS_DIR):
            group_path = os.path.join(RECORDS_DIR, group_folder)
            if os.path.isdir(group_path):
                record_file = os.path.join(group_path, 'recorded_users.txt')
                if os.path.exists(record_file):
                    with open(record_file, 'r', encoding='utf-8') as f:
                        user_ids = set(line.strip() for line in f)
                        self.recorded_users[group_folder] = user_ids
                else:
                    self.recorded_users[group_folder] = set()
                    
    def save_user_record(self, group_name, group_folder, user_id, username, name, last_seen, scan_date):
        """Kullanıcı bilgisini kaydeder (admin ve kurucular hariç)"""
        group_path = os.path.join(RECORDS_DIR, group_folder)
        if not os.path.exists(group_path):
            os.makedirs(group_path)
            
        if group_folder not in self.recorded_users:
            self.recorded_users[group_folder] = set()
            
        if user_id in self.recorded_users[group_folder]:
            return False
            
        csv_file = os.path.join(group_path, 'members.csv')
        file_exists = os.path.exists(csv_file)
        
        with open(csv_file, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['User ID', 'Username', 'Name', 'Son Görülme', 'İlk Görülme Tarihi', 'Grup Adı'])
            
            writer.writerow([
                user_id,
                username if username else 'yok',
                name if name else '-',
                last_seen,
                scan_date,
                group_name
            ])
            
        self.recorded_users[group_folder].add(user_id)
        
        record_file = os.path.join(group_path, 'recorded_users.txt')
        with open(record_file, 'a', encoding='utf-8') as f:
            f.write(f"{user_id}\n")
            
        return True
        
    def sanitize_folder_name(self, name):
        """Dosya sistemi için güvenli klasör adı"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        if len(name) > 50:
            name = name[:47] + '...'
        return name
        
    def format_last_seen(self, status):
        """Son görülme bilgisini formatlar"""
        if status is None:
            return "Uzun zaman önce"
        elif hasattr(status, 'was_online'):
            now = datetime.now(status.date.tzinfo)
            diff = now - status.date
            if diff.days > 0:
                return f"{diff.days} gün önce"
            elif diff.seconds > 3600:
                return f"{diff.seconds // 3600} saat önce"
            elif diff.seconds > 60:
                return f"{diff.seconds // 60} dakika önce"
            else:
                return "Şimdi"
        else:
            return "Bilinmiyor"
            
    async def is_user_admin(self, group, user_id):
        """Belirli bir kullanıcının admin olup olmadığını kontrol eder"""
        try:
            participant = await self.client.get_participant(group, user_id)
            if hasattr(participant, 'participant'):
                if participant.participant.is_admin or participant.participant.is_creator:
                    return True
        except Exception as e:
            # Kullanıcı bulunamazsa veya hata olursa admin değil varsay
            pass
        return False
        
    async def scan_group_messages(self, group):
        """Grup mesajlarını tarayarak aktif kullanıcıları bulur (adminler hariç)"""
        print(f"  📁 Taranıyor: {group.title}")
        
        try:
            # Son mesajları al
            history = await self.client(GetHistoryRequest(
                peer=group,
                limit=MESSAGE_LIMIT,
                offset_date=None,
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0
            ))
            
            users_found = set()
            for message in history.messages:
                if message.sender_id:
                    users_found.add(message.sender_id)
                if message.reply_to_msg_id:
                    try:
                        reply_msg = await self.client.get_messages(group, ids=message.reply_to_msg_id)
                        if reply_msg and reply_msg.sender_id:
                            users_found.add(reply_msg.sender_id)
                    except:
                        pass
            
            print(f"     Mesaj atan kullanıcılar: {len(users_found)}")
            
            new_users = []
            scan_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            group_folder = self.sanitize_folder_name(group.title)
            
            for user_id in users_found:
                try:
                    # Önce admin mi kontrol et
                    is_admin = await self.is_user_admin(group, user_id)
                    
                    if is_admin:
                        print(f"       ⏭️ Admin atlandı: ID:{user_id}")
                        continue
                        
                    user = await self.client.get_entity(user_id)
                    username = getattr(user, 'username', None)
                    name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
                    last_seen = self.format_last_seen(getattr(user, 'status', None))
                    
                    if self.save_user_record(group.title, group_folder, str(user_id), username, name, last_seen, scan_date):
                        new_users.append({
                            'user_id': user_id,
                            'username': username or 'yok',
                            'name': name or '-',
                            'last_seen': last_seen
                        })
                        print(f"       ✅ Yeni normal kullanıcı: {name} (@{username or 'yok'})")
                        
                except FloodWaitError as e:
                    print(f"       ⚠️ Rate limit: {e.seconds} saniye bekleniyor...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    continue
                    
            print(f"     📊 {group.title}: {len(new_users)} yeni normal kullanıcı kaydedildi")
            return group_folder, new_users
            
        except FloodWaitError as e:
            print(f"     ⚠️ Rate limit: {e.seconds} saniye bekleniyor...")
            await asyncio.sleep(e.seconds)
            return None, []
        except Exception as e:
            print(f"     ❌ Hata: {e}")
            return None, []
            
    async def send_telegram_report(self, new_users_by_group):
        """Telegram'a rapor gönderir"""
        total_new = sum(len(u) for u in new_users_by_group.values())
        
        if not new_users_by_group:
            await self.client.send_message(YOUR_USER_ID, f"📭 **{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}**\nBu taramada yeni normal kullanıcı bulunamadı.")
            return
            
        # Zip dosyası oluştur
        zip_filename = f"user_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for group_folder, users in new_users_by_group.items():
                if users:
                    csv_file = os.path.join(RECORDS_DIR, group_folder, f'new_users_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
                    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow(['User ID', 'Username', 'Name', 'Son Görülme'])
                        for user in users:
                            writer.writerow([user['user_id'], user['username'], user['name'], user['last_seen']])
                    zipf.write(csv_file, f"{group_folder}_yeni_normal_kullanicilar.csv")
                    os.remove(csv_file)
        
        # Zip dosyasını gönder
        caption = f"📊 **Tarama Raporu**\n📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📌 Toplam: {total_new} yeni normal kullanıcı"
        await self.client.send_file(YOUR_USER_ID, zip_filename, caption=caption)
        os.remove(zip_filename)
        
        # Özet mesaj gönder
        summary = "📋 **Grup Bazlı Özet (Normal Kullanıcılar):**\n\n"
        for group_folder, users in new_users_by_group.items():
            if users:
                summary += f"• `{group_folder}`: {len(users)} yeni kullanıcı\n"
        await self.client.send_message(YOUR_USER_ID, summary)
        
    async def scan_all_groups(self, scan_type="scheduled"):
        """Tüm grupları tarar"""
        start_time = datetime.now()
        
        # Tarama başladı mesajı
        await self.client.send_message(YOUR_USER_ID, f"🟢 **Tarama Başladı**\n⏰ Saat: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n📌 Tip: {'İlk Tarama' if scan_type == 'first' else 'Planlı Tarama'}")
        
        print(f"\n{'='*60}")
        print(f"Tarama başladı: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        try:
            dialogs = await self.client.get_dialogs()
            groups = [d for d in dialogs if d.is_group or d.is_channel]
            
            print(f"\nToplam {len(groups)} grup bulundu.\n")
            
            new_users_by_group = {}
            
            for i, group in enumerate(groups, 1):
                print(f"[{i}/{len(groups)}]", end=" ")
                group_folder, new_users = await self.scan_group_messages(group.entity)
                if new_users:
                    new_users_by_group[group_folder] = new_users
                await asyncio.sleep(2)
                
            # Tarama tamamlandı mesajı ve rapor
            end_time = datetime.now()
            total_new = sum(len(u) for u in new_users_by_group.values())
            
            await self.send_telegram_report(new_users_by_group)
            await self.client.send_message(YOUR_USER_ID, f"🔴 **Tarama Tamamlandı**\n⏰ Saat: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n⏱️ Süre: {(end_time - start_time).seconds} saniye\n📊 Toplam: {total_new} yeni normal kullanıcı")
            
            # Hata raporu sıfırlama (başarılı tarama yapıldı)
            self.error_reported = False
            
            print(f"\n{'='*60}")
            print(f"Tarama tamamlandı: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Toplam {total_new} yeni normal kullanıcı kaydedildi.")
            print(f"{'='*60}\n")
            
        except Exception as e:
            error_msg = f"❌ **HATA!** Tarama sırasında hata oluştu:\n{str(e)}"
            await self.client.send_message(YOUR_USER_ID, error_msg)
            print(error_msg)
            
    async def check_missed_scans(self):
        """Sadece saat geldiği halde tarama olmadıysa uyarı verir"""
        now = datetime.now()
        today = now.date()
        current_hour = now.hour
        
        # Sadece şu anki saat bir tarama saatine eşitse ve tarama yapılmamışsa
        if current_hour in SCAN_HOURS:
            if now.minute >= 5:  # Saat 5 dakika geçtiyse
                if str(today) not in self.last_scan_dates:
                    self.last_scan_dates[str(today)] = []
                if current_hour not in self.last_scan_dates[str(today)]:
                    if not self.error_reported:
                        await self.client.send_message(YOUR_USER_ID, f"⚠️ **UYARI!**\n⏰ Saat {current_hour:02d}:00 taraması gerçekleşmedi!\n📅 Tarih: {today}\nBot yeniden başlatılmayı deneyecek...")
                        self.error_reported = True
                        
    async def run_scheduled_scanner(self):
        """Planlanmış saatlerde tarama yapar"""
        await self.client.start()
        
        # Başlangıç mesajı
        await self.client.send_message(YOUR_USER_ID, f"✅ **Tarayıcı Başlatıldı**\n⏰ Çalışma Saatleri: {', '.join(f'{h:02d}:00' for h in SCAN_HOURS)}\n📌 Sadece normal kullanıcılar kaydedilecek (adminler hariç)\n📌 İlk tarama hemen başlıyor...")
        
        print("Telegram Kullanıcı Tarayıcı Başladı")
        print(f"Tarama saatleri: {', '.join(f'{h:02d}:00' for h in SCAN_HOURS)}")
        print("NOT: Admin ve kurucular kaydedilmeyecek, sadece normal kullanıcılar")
        
        # İLK TARAMAYI HEMEN YAP
        print("\n🚀 İlk tarama hemen başlıyor...")
        await self.scan_all_groups(scan_type="first")
        print("✅ İlk tarama tamamlandı, planlı taramalara geçiliyor.\n")
        
        # Tarama kayıtlarını tut
        last_scan_records = {h: None for h in SCAN_HOURS}
        
        while True:
            try:
                now = datetime.now()
                current_hour = now.hour
                current_minute = now.minute
                
                for scan_hour in SCAN_HOURS:
                    # Saat tam olarak geldiğinde ve henüz bu saatte tarama yapılmamışsa
                    if current_hour == scan_hour and current_minute == 0:
                        if last_scan_records[scan_hour] != now.date():
                            last_scan_records[scan_hour] = now.date()
                            # Bugün bu saat için tarama yapıldığını kaydet
                            if str(now.date()) not in self.last_scan_dates:
                                self.last_scan_dates[str(now.date())] = []
                            if scan_hour not in self.last_scan_dates[str(now.date())]:
                                self.last_scan_dates[str(now.date())].append(scan_hour)
                            # Taramayı başlat
                            await self.scan_all_groups(scan_type="scheduled")
                            await asyncio.sleep(60)  # Aynı saatte tekrar tetiklenmemesi için
                            
                # Kaçırılan taramaları kontrol et
                await self.check_missed_scans()
                
            except Exception as e:
                # Bot kapanmasın, hatayı bildir ve devam et
                if not self.error_reported:
                    await self.client.send_message(YOUR_USER_ID, f"⚠️ **Bot Hatası**\nHata: {str(e)}\nBot çalışmaya devam ediyor, müdahale gerekebilir.")
                    self.error_reported = True
                print(f"⚠️ Döngü hatası: {e}, devam ediliyor...")
                
            await asyncio.sleep(30)  # Her 30 saniyede bir kontrol

async def main():
    scanner = GroupUserScanner()
    scanner.load_records()
    await scanner.run_scheduled_scanner()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Tarayıcı durduruldu.")
    except Exception as e:
        print(f"\n❌ Kritik hata: {e}")
        input("Çıkmak için Enter'a basın...")
