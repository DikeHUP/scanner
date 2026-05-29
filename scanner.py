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

# Adminleri KAYDETME (False = sadece normal kullanıcılar)
INCLUDE_ADMINS = False

# Hash storage
HASH_STORAGE_DIR = 'hash_storage'
# =======================================================

class GroupUserScanner:
    def __init__(self):
        self.client = TelegramClient('user_scanner', API_ID, API_HASH)
        self.recorded_users = set()  # TEK SET: tüm kayıtlı kullanıcılar
        self.user_hashes = {}  # {user_id: access_hash}
        self.last_scan_dates = {}
        self.error_reported = False
        
    def load_records(self):
        """Daha önce kaydedilmiş kullanıcıları ve hash'leri yükler"""
        # Hash storage klasörü
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
        
        # Kayıtlı kullanıcıları yükle (TEK CSV'den)
        csv_file = os.path.join(HASH_STORAGE_DIR, 'all_users.csv')
        if os.path.exists(csv_file):
            try:
                with open(csv_file, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    next(reader, None)  # Başlık satırını atla
                    for row in reader:
                        if row:
                            self.recorded_users.add(row[0])  # ID'yi ekle
            except:
                pass
                    
    def save_user_record(self, user_id, access_hash, username, name, last_seen, scan_date):
        """Kullanıcı bilgisini TEK CSV dosyasına kaydeder"""
        if str(user_id) in self.recorded_users:
            return False
        
        # Hash'i kaydet
        if access_hash:
            self.user_hashes[str(user_id)] = access_hash
            hash_file = os.path.join(HASH_STORAGE_DIR, 'user_hashes.json')
            with open(hash_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_hashes, f, indent=2, ensure_ascii=False)
        
        # TEK CSV dosyasına kaydet
        csv_file = os.path.join(HASH_STORAGE_DIR, 'all_users.csv')
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
        
        self.recorded_users.add(str(user_id))
        return True
        
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
                    
                    if self.save_user_record(user_id, access_hash, username, name, last_seen, scan_date):
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
            return new_users
            
        except FloodWaitError as e:
            print(f"     ⚠️ Rate limit: {e.seconds} saniye bekleniyor...")
            await asyncio.sleep(e.seconds)
            return []
        except Exception as e:
            print(f"     ❌ Hata: {e}")
            return []
            
    async def send_telegram_report(self, new_users):
        """Telegram'a rapor gönderir (SADECE TEK CSV)"""
        if not new_users:
            await self.client.send_message(YOUR_USER_ID, f"📭 **{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}**\nBu taramada yeni kullanıcı bulunamadı.")
            return
        
        # Sadece yeni kullanıcıların olduğu geçici CSV oluştur
        temp_csv = f"temp_new_users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(temp_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['User ID', 'Access Hash', 'Username', 'Name', 'Son Görülme'])
            for user in new_users:
                writer.writerow([
                    user['user_id'],
                    user['access_hash'] if user['access_hash'] else 'HASH_YOK',
                    user['username'],
                    user['name'],
                    user['last_seen']
                ])
        
        # Zip oluştur
        zip_filename = f"user_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(temp_csv, f"yeni_normal_kullanicilar.csv")
        
        os.remove(temp_csv)
        
        # Zip'i gönder
        caption = f"📊 **Tarama Raporu**\n📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📌 Toplam: {len(new_users)} yeni normal kullanıcı\n🔑 ID + HASH birlikte"
        await self.client.send_file(YOUR_USER_ID, zip_filename, caption=caption)
        os.remove(zip_filename)
        
        # Hash dosyasını da ayrıca gönder
        hash_file = os.path.join(HASH_STORAGE_DIR, 'user_hashes.json')
        if os.path.exists(hash_file):
            await self.client.send_file(YOUR_USER_ID, hash_file, caption="🔑 **Access Hash Veritabanı** (Birleştirici için)")
        
    async def scan_all_groups(self, scan_type="scheduled"):
        """Tüm grupları tarar"""
        start_time = datetime.now()
        
        await self.client.send_message(YOUR_USER_ID, f"🟢 **Tarama Başladı**\n⏰ Saat: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n📌 Tip: {'İlk Tarama' if scan_type == 'first' else 'Planlı Tarama'}\n🔑 Sadece NORMAL kullanıcılar kaydedilecek")
        
        print(f"\n{'='*60}")
        print(f"Tarama başladı: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Sadece NORMAL kullanıcılar kaydedilecek (Adminler ATLANACAK)")
        print(f"{'='*60}")
        
        try:
            dialogs = await self.client.get_dialogs()
            groups = [d for d in dialogs if d.is_group or d.is_channel]
            
            print(f"\nToplam {len(groups)} grup bulundu.\n")
            
            all_new_users = []
            
            for i, group in enumerate(groups, 1):
                print(f"[{i}/{len(groups)}]", end=" ")
                new_users = await self.scan_group_messages(group.entity)
                all_new_users.extend(new_users)
                await asyncio.sleep(2)
                
            end_time = datetime.now()
            
            await self.send_telegram_report(all_new_users)
            
            hash_count = len(self.user_hashes)
            await self.client.send_message(YOUR_USER_ID, f"🔴 **Tarama Tamamlandı**\n⏰ Saat: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n⏱️ Süre: {(end_time - start_time).seconds} saniye\n📊 Toplam: {len(all_new_users)} yeni kullanıcı\n🔑 Toplam Hash: {hash_count}")
            
            self.error_reported = False
            
            print(f"\n{'='*60}")
            print(f"Tarama tamamlandı: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Toplam {len(all_new_users)} yeni kullanıcı kaydedildi.")
            print(f"Toplam {hash_count} access_hash toplandı.")
            print(f"{'='*60}\n")
            
        except Exception as e:
            error_msg = f"❌ **HATA!** Tarama sırasında hata oluştu:\n{str(e)}"
            await self.client.send_message(YOUR_USER_ID, error_msg)
            print(error_msg)
            
    async def run_scheduled_scanner(self):
        """Planlanmış saatlerde tarama yapar"""
        await self.client.start()
        
        await self.client.send_message(YOUR_USER_ID, f"✅ **Tarayıcı Başlatıldı**\n⏰ Çalışma Saatleri: {', '.join(f'{h:02d}:00' for h in SCAN_HOURS)}\n🔑 Sadece NORMAL kullanıcılar kaydedilecek\n📌 Adminler otomatik atlanacak\n📌 İlk tarama hemen başlıyor...")
        
        print("Telegram Kullanıcı Tarayıcı Başladı")
        print(f"Tarama saatleri: {', '.join(f'{h:02d}:00' for h in SCAN_HOURS)}")
        print("Sadece NORMAL kullanıcılar kaydedilecek (Adminler ATLANACAK)")
        
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
