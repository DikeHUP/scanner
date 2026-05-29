import asyncio
import csv
import os
import zipfile
import json
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import FloodWaitError

# ==================== KONFIGÜRASYON ====================
API_ID = 31318870
API_HASH = '7f5771aa235fbfbf66722f1b9516da45'
YOUR_USER_ID = '@merhababendike'
SCAN_HOURS = [0, 12, 18]
MESSAGE_LIMIT = 2500

# Hash storage
HASH_STORAGE_DIR = 'hash_storage'
RECORDS_DIR = 'user_records'  # Grup bazlı kayıtlar için
# =======================================================

class GroupUserScanner:
    def __init__(self):
        self.client = TelegramClient('user_scanner', API_ID, API_HASH)
        self.user_hashes = {}  # {user_id: access_hash}
        self.group_user_sets = {}  # {group_folder: set(user_ids)} - Her grup için ayrı set
        self.last_scan_dates = {}
        self.error_reported = False
        
    def load_records(self):
        """Daha önce kaydedilmiş kullanıcıları ve hash'leri yükler"""
        # Hash storage
        if not os.path.exists(HASH_STORAGE_DIR):
            os.makedirs(HASH_STORAGE_DIR)
        
        # Hash'leri yükle
        hash_file = os.path.join(HASH_STORAGE_DIR, 'user_hashes.json')
        if os.path.exists(hash_file):
            try:
                with open(hash_file, 'r', encoding='utf-8') as f:
                    self.user_hashes = json.load(f)
            except:
                self.user_hashes = {}
        
        # Grup bazlı kayıtları yükle
        if not os.path.exists(RECORDS_DIR):
            os.makedirs(RECORDS_DIR)
        
        for group_folder in os.listdir(RECORDS_DIR):
            group_path = os.path.join(RECORDS_DIR, group_folder)
            if os.path.isdir(group_path):
                record_file = os.path.join(group_path, 'recorded_users.txt')
                if os.path.exists(record_file):
                    with open(record_file, 'r', encoding='utf-8') as f:
                        user_ids = set(line.strip() for line in f)
                        self.group_user_sets[group_folder] = user_ids
                else:
                    self.group_user_sets[group_folder] = set()
                    
    def save_user_record(self, group_folder, user_id, access_hash, username, name, last_seen, scan_date):
        """Kullanıcı bilgisini GRUP BAZLI CSV'ye kaydeder"""
        group_path = os.path.join(RECORDS_DIR, group_folder)
        if not os.path.exists(group_path):
            os.makedirs(group_path)
        
        if group_folder not in self.group_user_sets:
            self.group_user_sets[group_folder] = set()
        
        if str(user_id) in self.group_user_sets[group_folder]:
            return False
        
        # Hash'i kaydet
        if access_hash:
            self.user_hashes[str(user_id)] = access_hash
            hash_file = os.path.join(HASH_STORAGE_DIR, 'user_hashes.json')
            with open(hash_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_hashes, f, indent=2, ensure_ascii=False)
        
        # Grup CSV'sine kaydet
        csv_file = os.path.join(group_path, 'members.csv')
        file_exists = os.path.exists(csv_file)
        
        with open(csv_file, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['User ID', 'Access Hash', 'Username', 'Name', 'Son Görülme', 'İlk Görülme'])
            
            writer.writerow([
                user_id,
                access_hash if access_hash else 'HASH_YOK',
                username if username else 'yok',
                name if name else '-',
                last_seen,
                scan_date
            ])
        
        self.group_user_sets[group_folder].add(str(user_id))
        
        # Kayıt dosyasını güncelle
        record_file = os.path.join(group_path, 'recorded_users.txt')
        with open(record_file, 'a', encoding='utf-8') as f:
            f.write(f"{user_id}\n")
        
        return True
        
    def sanitize_folder_name(self, name):
        """Dosya sistemi için güvenli klasör adı"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        # Telefon ve özel karakterleri koru (emoji vb.)
        if len(name) > 100:
            name = name[:97] + '...'
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
        except:
            pass
        return False
        
    async def scan_group_messages(self, group):
        """Grup mesajlarını tarayarak NORMAL kullanıcıları bulur (adminler hariç)"""
        print(f"  📁 Taranıyor: {group.title}")
        
        try:
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
                    # Admin mi kontrol et - Admin ise ATLA
                    is_admin = await self.is_user_admin(group, user_id)
                    if is_admin:
                        print(f"       ⏭️ Admin atlandı: ID:{user_id}")
                        continue
                        
                    user = await self.client.get_entity(user_id)
                    
                    # access_hash'i al
                    access_hash = None
                    if hasattr(user, 'access_hash'):
                        access_hash = user.access_hash
                    
                    username = getattr(user, 'username', None)
                    name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
                    last_seen = self.format_last_seen(getattr(user, 'status', None))
                    
                    if self.save_user_record(group_folder, user_id, access_hash, username, name, last_seen, scan_date):
                        new_users.append({
                            'user_id': user_id,
                            'access_hash': access_hash,
                            'username': username or 'yok',
                            'name': name or '-',
                            'last_seen': last_seen
                        })
                        print(f"       ✅ Yeni kullanıcı: {name} (@{username or 'yok'}) [ID:{user_id}]")
                        
                except FloodWaitError as e:
                    print(f"       ⚠️ Rate limit: {e.seconds} saniye bekleniyor...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    continue
                    
            print(f"     📊 {group.title}: {len(new_users)} yeni kullanıcı kaydedildi")
            return group_folder, new_users
            
        except FloodWaitError as e:
            print(f"     ⚠️ Rate limit: {e.seconds} saniye bekleniyor...")
            await asyncio.sleep(e.seconds)
            return None, []
        except Exception as e:
            print(f"     ❌ Hata: {e}")
            return None, []
            
    async def send_telegram_report(self, new_users_by_group):
        """Telegram'a rapor gönderir (Her grup için ayrı CSV)"""
        total_new = sum(len(u) for u in new_users_by_group.values())
        
        if not new_users_by_group:
            await self.client.send_message(YOUR_USER_ID, f"📭 **{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}**\nBu taramada yeni kullanıcı bulunamadı.")
            return
        
        # Zip dosyası oluştur
        zip_filename = f"user_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for group_folder, users in new_users_by_group.items():
                if users:
                    # Geçici CSV oluştur
                    temp_csv = f"temp_{group_folder}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                    with open(temp_csv, 'w', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow(['User ID', 'Access Hash', 'Username', 'Name', 'Son Görülme'])
                        for user in users:
                            writer.writerow([
                                user['user_id'],
                                user['access_hash'] if user['access_hash'] else 'HASH_YOK',
                                user['username'],
                                user['name'],
                                user['last_seen']
                            ])
                    
                    # Zip'e ekle
                    zipf.write(temp_csv, f"{group_folder}_yeni_normal_kullanicilar.csv")
                    os.remove(temp_csv)
        
        # Zip'i gönder
        caption = f"📊 **Tarama Raporu**\n📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📌 Toplam: {total_new} yeni normal kullanıcı\n🔑 ID + HASH birlikte\n📁 {len(new_users_by_group)} grup ayrı ayrı"
        await self.client.send_file(YOUR_USER_ID, zip_filename, caption=caption)
        os.remove(zip_filename)
        
        # Hash dosyasını da ayrıca gönder
        hash_file = os.path.join(HASH_STORAGE_DIR, 'user_hashes.json')
        if os.path.exists(hash_file):
            await self.client.send_file(YOUR_USER_ID, hash_file, caption="🔑 **Access Hash Veritabanı** (Birleştirici için)")
        
        # Özet mesaj
        summary = "📋 **Grup Bazlı Özet:**\n\n"
        for group_folder, users in new_users_by_group.items():
            if users:
                summary += f"• `{group_folder}`: {len(users)} yeni kullanıcı\n"
        await self.client.send_message(YOUR_USER_ID, summary)
        
    async def scan_all_groups(self, scan_type="scheduled"):
        """Tüm grupları tarar"""
        start_time = datetime.now()
        
        await self.client.send_message(YOUR_USER_ID, f"🟢 **Tarama Başladı**\n⏰ Saat: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n📌 Tip: {'İlk Tarama' if scan_type == 'first' else 'Planlı Tarama'}\n🔑 Sadece NORMAL kullanıcılar kaydedilecek\n📁 Gruplar ayrı ayrı işlenecek")
        
        print(f"\n{'='*60}")
        print(f"Tarama başladı: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Sadece NORMAL kullanıcılar kaydedilecek (Adminler ATLANACAK)")
        print(f"Gruplar ayrı ayrı işlenecek")
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
                
            end_time = datetime.now()
            
            await self.send_telegram_report(new_users_by_group)
            
            hash_count = len(self.user_hashes)
            total_new = sum(len(u) for u in new_users_by_group.values())
            await self.client.send_message(YOUR_USER_ID, f"🔴 **Tarama Tamamlandı**\n⏰ Saat: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n⏱️ Süre: {(end_time - start_time).seconds} saniye\n📊 Toplam: {total_new} yeni kullanıcı\n🔑 Toplam Hash: {hash_count}\n📁 {len(new_users_by_group)} grupta kullanıcı bulundu")
            
            self.error_reported = False
            
            print(f"\n{'='*60}")
            print(f"Tarama tamamlandı: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Toplam {total_new} yeni kullanıcı kaydedildi.")
            print(f"Toplam {hash_count} access_hash toplandı.")
            print(f"{'='*60}\n")
            
        except Exception as e:
            error_msg = f"❌ **HATA!** Tarama sırasında hata oluştu:\n{str(e)}"
            await self.client.send_message(YOUR_USER_ID, error_msg)
            print(error_msg)
            
    async def run_scheduled_scanner(self):
        """Planlanmış saatlerde tarama yapar"""
        await self.client.start()
        
        await self.client.send_message(YOUR_USER_ID, f"✅ **Tarayıcı Başlatıldı**\n⏰ Çalışma Saatleri: {', '.join(f'{h:02d}:00' for h in SCAN_HOURS)}\n🔑 Sadece NORMAL kullanıcılar kaydedilecek\n📌 Adminler otomatik atlanacak\n📁 Gruplar ayrı ayrı işlenecek\n📌 İlk tarama hemen başlıyor...")
        
        print("Telegram Kullanıcı Tarayıcı Başladı")
        print(f"Tarama saatleri: {', '.join(f'{h:02d}:00' for h in SCAN_HOURS)}")
        print("Sadece NORMAL kullanıcılar kaydedilecek (Adminler ATLANACAK)")
        print("Gruplar ayrı ayrı işlenecek")
        
        # İLK TARAMA
        print("\n🚀 İlk tarama hemen başlıyor...")
        await self.scan_all_groups(scan_type="first")
        
        print("✅ İlk tarama tamamlandı, planlı taramalara geçiliyor.\n")
        
        last_scan_records = {h: None for h in SCAN_HOURS}
        
        while True:
            try:
                now = datetime.now()
                current_hour = now.hour
                current_minute = now.minute
                
                for scan_hour in SCAN_HOURS:
                    if current_hour == scan_hour and current_minute == 0:
                        if last_scan_records[scan_hour] != now.date():
                            last_scan_records[scan_hour] = now.date()
                            await self.scan_all_groups(scan_type="scheduled")
                            await asyncio.sleep(60)
                            
            except Exception as e:
                if not self.error_reported:
                    await self.client.send_message(YOUR_USER_ID, f"⚠️ **Bot Hatası**\nHata: {str(e)}\nBot çalışmaya devam ediyor.")
                    self.error_reported = True
                print(f"⚠️ Döngü hatası: {e}, devam ediliyor...")
                
            await asyncio.sleep(30)

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
