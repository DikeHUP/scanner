import asyncio
import csv
import os
import zipfile
import json
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import FloodWaitError, PeerFloodError

# ==================== KONFIGÜRASYON ====================
API_ID = 31318870
API_HASH = '7f5771aa235fbfbf66722f1b9516da45'
YOUR_USER_ID = '@merhababendike'
SCAN_HOURS = [0, 12, 18]
MESSAGE_LIMIT = 2500

# Hash storage
HASH_STORAGE_DIR = 'hash_storage'
RECORDS_DIR = 'user_records'
# =======================================================

class GroupUserScanner:
    def __init__(self):
        self.client = TelegramClient('user_scanner', API_ID, API_HASH)
        self.user_hashes = {}
        self.group_user_sets = {}
        self.error_reported = False
        
    def load_records(self):
        if not os.path.exists(HASH_STORAGE_DIR):
            os.makedirs(HASH_STORAGE_DIR)
        
        hash_file = os.path.join(HASH_STORAGE_DIR, 'user_hashes.json')
        if os.path.exists(hash_file):
            try:
                with open(hash_file, 'r', encoding='utf-8') as f:
                    self.user_hashes = json.load(f)
            except Exception as e:
                print(f"Hash dosyası okuma hatası: {e}")
                self.user_hashes = {}
        
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
        group_path = os.path.join(RECORDS_DIR, group_folder)
        if not os.path.exists(group_path):
            os.makedirs(group_path)
        
        if group_folder not in self.group_user_sets:
            self.group_user_sets[group_folder] = set()
        
        if str(user_id) in self.group_user_sets[group_folder]:
            return False
        
        if access_hash:
            self.user_hashes[str(user_id)] = access_hash
            hash_file = os.path.join(HASH_STORAGE_DIR, 'user_hashes.json')
            with open(hash_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_hashes, f, indent=2, ensure_ascii=False)
        
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
        
        record_file = os.path.join(group_path, 'recorded_users.txt')
        with open(record_file, 'a', encoding='utf-8') as f:
            f.write(f"{user_id}\n")
        
        return True
        
    def sanitize_folder_name(self, name):
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        if len(name) > 100:
            name = name[:97] + '...'
        return name
        
    def format_last_seen(self, status):
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
        try:
            participant = await self.client.get_participant(group, user_id)
            if hasattr(participant, 'participant'):
                if participant.participant.is_admin or participant.participant.is_creator:
                    return True
        except Exception as e:
            print(f"🔐 Admin kontrol hatası (grup: {getattr(group, 'title', '?')}, user: {user_id}): {type(e).__name__} - {e}")
        return False
        
    async def scan_group_messages(self, group):
        print(f"  📁 {group.title}")
        
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
                    except Exception as e:
                        print(f"  ⚠️ Reply mesaj hatası (msg {message.id}): {type(e).__name__}")
                        pass
            
            new_users = []
            scan_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            group_folder = self.sanitize_folder_name(group.title)
            
            for user_id in users_found:
                try:
                    is_admin = await self.is_user_admin(group, user_id)
                    if is_admin:
                        continue
                        
                    user = await self.client.get_entity(user_id)
                    
                    if user.bot:
                        continue
                    
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
                        
                except FloodWaitError as e:
                    print(f"  ⏳ FloodWait (user {user_id}): {e.seconds} saniye bekle")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    print(f"  ❌ Kullanıcı {user_id} işlenirken hata: {type(e).__name__} - {e}")
                    continue
                    
            return group_folder, new_users
            
        except FloodWaitError as e:
            print(f"  🚫 Grup {group.title} FloodWait: {e.seconds} saniye")
            await asyncio.sleep(e.seconds)
            return None, []
        except Exception as e:
            print(f"  ❌ Grup {group.title} taranırken hata: {type(e).__name__} - {e}")
            return None, []
            
    async def send_telegram_report(self, new_users_by_group):
        total_new = sum(len(u) for u in new_users_by_group.values())
        
        if not new_users_by_group:
            print("📭 Yeni kullanıcı yok, rapor gönderilmedi.")
            return
        
        zip_filename = f"user_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for group_folder, users in new_users_by_group.items():
                if users:
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
                    
                    zipf.write(temp_csv, f"{group_folder}_yeni_normal_kullanicilar.csv")
                    os.remove(temp_csv)
        
        # Sadece zip gönder, başka mesaj yok
        caption = f"📊 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {total_new} yeni kullanıcı"
        
        try:
            await self.client.send_file(YOUR_USER_ID, zip_filename, caption=caption)
            print(f"📤 Rapor zip'i ({zip_filename}) gönderildi.")
        except (FloodWaitError, PeerFloodError) as e:
            print(f"⚠️ Rapor gönderme hatası (zip): {type(e).__name__} - {e}")
            # Zip'i silmeden önce logla
        except Exception as e:
            print(f"❌ Rapor gönderme hatası (zip): {type(e).__name__} - {e}")
        
        try:
            os.remove(zip_filename)
        except:
            pass
        
        # Hash dosyasını gönder
        hash_file = os.path.join(HASH_STORAGE_DIR, 'user_hashes.json')
        if os.path.exists(hash_file):
            try:
                await self.client.send_file(YOUR_USER_ID, hash_file, caption="🔑 Hash DB")
                print("📤 Hash DB dosyası gönderildi.")
            except Exception as e:
                print(f"⚠️ Hash DB gönderme hatası: {type(e).__name__} - {e}")
        
    async def scan_all_groups(self):
        start_time = datetime.now()
        print(f"\n🔍 Tarama başladı: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            dialogs = await self.client.get_dialogs()
            groups = [d for d in dialogs if d.is_group or d.is_channel]
            print(f"📡 Toplam dialog: {len(dialogs)}, Grup/Kanal: {len(groups)}")
            
            new_users_by_group = {}
            
            for group in groups:
                print(f"\n🔎 Taranıyor: {group.title}")
                group_folder, new_users = await self.scan_group_messages(group.entity)
                if new_users:
                    new_users_by_group[group_folder] = new_users
                    print(f"   ✅ {len(new_users)} yeni kullanıcı bulundu.")
                else:
                    print(f"   ℹ️ Yeni kullanıcı yok.")
                await asyncio.sleep(2)
                
            await self.send_telegram_report(new_users_by_group)
            
            self.error_reported = False
            print(f"✅ Tarama tamamlandı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            
        except Exception as e:
            print(f"🔥 scan_all_groups hatası: {type(e).__name__} - {e}")
            
    async def run_scheduled_scanner(self):
        await self.client.start()
        print("✅ Client başlatıldı, oturum açıldı.")
        
        # İlk tarama
        await self.scan_all_groups()
        
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
                            print(f"⏰ Zamanlanmış tarama başlıyor: {now.strftime('%Y-%m-%d %H:%M:%S')}")
                            await self.scan_all_groups()
                            await asyncio.sleep(60)
                            
            except Exception as e:
                print(f"🔄 Döngü hatası: {type(e).__name__} - {e}")
                
            await asyncio.sleep(30)

async def main():
    scanner = GroupUserScanner()
    scanner.load_records()
    await scanner.run_scheduled_scanner()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Durduruldu.")
    except Exception as e:
        print(f"💥 Beklenmeyen hata: {type(e).__name__} - {e}")
