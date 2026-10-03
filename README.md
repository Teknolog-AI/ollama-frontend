# Gürkan AI — Ollama sohbeti ve GitHub araması

HTML/CSS/JavaScript arayüzü, Python/FastAPI backend'i ve bilgisayarınızdaki Ollama ile çalışan sohbet uygulaması. Model, GitHub'da herkese açık depoları arayabilir. Arayüz ve API aynı sunucudan açılır.

## Gereksinimler

- Python **3.11 veya üzeri** (test ortamı: Python 3.12).
- Güncel Ollama ve araç çağırmayı destekleyen, bilgisayarınıza indirilmiş bir model.
- GitHub araması için internet bağlantısı. Normal yerel sohbet için GitHub bağlantısı gerekmez.
- Node.js **24.15.0 veya üzeri bir LTS sürümü** yalnızca arayüz testleri için gerekir. Güncel 22.x sürümleri de 22.22.2'den itibaren desteklenir.

## Windows / PowerShell ile çalıştırma

Komutları proje kökünde, `backend` ve `frontend` klasörlerinin bulunduğu yerde çalıştırın:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Ollama uygulamasını açın. Ollama zaten çalışmıyorsa ayrı bir terminalde `ollama serve` çalıştırabilirsiniz. Kullanmak istediğiniz modeli indirin:

```powershell
ollama pull qwen3.5:4b-q4_K_M
ollama list
```

`gurkan-ai` özel bir model adıdır; bu depo onun Modelfile'ını içermez. Kendi bilgisayarınızda oluşturmadıysanız listede görünmez. Başlangıç için Qwen modeli yeterlidir.

Backend ve arayüzü başlatın:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Tarayıcıda **http://127.0.0.1:8000** adresini açın. API açıklamaları **http://127.0.0.1:8000/docs** adresindedir. HTML dosyasını doğrudan açmayın; Live Server'a ihtiyaç yoktur.

Linux/macOS'ta sanal ortamı `python3 -m venv .venv` ile oluşturun ve komutlardaki Python yolunu `.venv/bin/python` olarak kullanın.

## Kullanım

- Modeller yüklenene kadar mesaj gönderilemez. Yalnızca izin verilen ve Ollama'da kurulu modeller gösterilir.
- Enter mesaj gönderir; Shift + Enter yeni satır ekler.
- Başarısız mesaj geçmişe eklenmez. Düzenleyip gönderme veya **Mesajı yeniden dene** aynı mesaj balonunu kullanır.
- **Durdur** tarayıcı isteğini iptal eder. Backend bağlantının kapandığını gördüğünde devam eden servis görevini de iptal eder. Ollama'nın GPU çalışmasını ne zaman bitirdiği kullanılan Ollama sürümüne bağlıdır.
- **Yeni sohbet** ve model değişikliği mevcut sohbeti temizler; devam eden cevabın yeni sohbete karışması önlenir.
- **Bu cihazda sohbeti hatırla** isteğe bağlıdır ve başlangıçta kapalıdır. Açıldığında yalnızca tamamlanmış konuşmalar, seçilen modelle birlikte tarayıcının localStorage alanına kaydedilir. Kapatmak kaydı siler; yeni sohbet eski kaydı temizler. Bu kayıt sunucuda/veritabanında tutulmaz ve cihazlar arasında eşitlenmez.

Örnekler: “Express.js middleware nedir?” veya “GitHub'da FastAPI başlangıç projeleri bul.”

## Ayarlar

`.env.example` örneğini `.env` olarak kopyalayın. `.env` Git'e gönderilmez. Değişikliklerden sonra sunucuyu yeniden başlatın.

| Ayar | Varsayılan | Açıklama |
| --- | --- | --- |
| OLLAMA_BASE_URL | http://127.0.0.1:11434 | Ollama sunucusu |
| ALLOWED_MODELS | Qwen ve gurkan-ai | JSON dizisi; kurulu modellerle kesişimi gösterilir |
| OLLAMA_TIMEOUT_SECONDS | 120 | Tek Ollama isteğinin bekleme süresi |
| MODEL_LIST_TIMEOUT_SECONDS | 10 | Model listesinin bekleme süresi |
| CHAT_TIMEOUT_SECONDS | 180 | Araçlar dahil bütün sohbet isteğinin üst süresi |
| MAX_TOOL_ROUNDS | 3 | En fazla araç turu; ardından son cevap beklenir |
| MAX_TOOL_CALLS | 10 | Bütün turlardaki toplam araç çağrısı sınırı |
| GITHUB_TIMEOUT_SECONDS | 15 | GitHub isteğinin bekleme süresi |
| GITHUB_TOKEN | boş | İsteğe bağlı; yalnızca backend'de kullanılır |
| GITHUB_API_URL | https://api.github.com | GitHub API adresi |
| GITHUB_API_VERSION | 2026-03-10 | GitHub API sürümü |
| CORS_ORIGINS | [] | Ayrı bir arayüz sunucusu kullanılırsa izin verilecek tam adresler |

Örnek model listesi: `ALLOWED_MODELS=["qwen3.5:4b-q4_K_M","gurkan-ai"]`.
Etiketi yazılmayan model adları `:latest` ile eşleştirilir. Araç desteği olmayan modeller GitHub araması için uygun değildir.

Sohbet sınırları `backend/models.py` içinde tanımlıdır: mesaj başına 8.000 karakter; bir istekte en fazla 40 mesaj ve toplam 64.000 karakter. Arayüz bu sınırları backend'den alır. Sınıra ulaşıldığında yeni sohbet başlatın; eski mesajlar sessizce kırpılmaz.

## Dosya düzeni

| Dosya | Sorumluluk |
| --- | --- |
| backend/main.py | API yolları, servis yaşam döngüsü, iptal ve arayüz sunumu |
| backend/config.py | Ortam ayarları ve model adı eşleştirme |
| backend/models.py | İstek doğrulama ve sohbet sınırları |
| backend/errors.py | Kullanıcıya dönen servis hataları |
| backend/services/ollama.py | Model listesi ve Ollama bağlantısı |
| backend/services/github.py | GitHub araması ve kullanım sınırı yönetimi |
| backend/services/chat.py | Sınırlı araç çağrısı döngüsü |
| frontend/chat-state.js | Sohbet geçmişi ve cevap doğrulama |
| frontend/index.js | Arayüz, yeniden deneme, iptal ve cihazdaki kayıt |

## API

- `GET /models`: kurulu ve izinli modeller; arayüz için sınırlar ve bekleme süresi.
- `POST /chat`: `model` ve kullanıcı/asistan mesajlarından oluşan `messages`.
- `GET /github/search?query=fastapi&limit=5`: 2–200 karakter sorgu; 1–10 sonuç.
- `GET /health`: backend ayakta mı? Ollama veya GitHub'ın hazır olduğunu garanti etmez.

Hatalar `detail` (okunabilir açıklama) ve `code` alanlarıyla döner. Eksik model 404, bağlantısı kapalı Ollama 503, zaman aşımı 504, GitHub kullanım sınırı 429 verir. Varsa `Retry-After` bekleme süresi aktarılır. Her 403 cevabı kullanım sınırı sayılmaz.

## Testler

Backend testleri gerçek FastAPI/HTTPX kullanır; dış Ollama/GitHub cevapları kontrollü olarak taklit edilir. GPU veya erişim anahtarı gerekmez:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Arayüz mantığı ve DOM testleri için (gerçek tarayıcı gerektirmez):

```powershell
npm ci
npm test
```

Yalnızca sohbet mantığını bağımlılık kurmadan kontrol etmek için `npm run test:unit` kullanılabilir. Görsel tarayıcı testleri için ayrıca:

```powershell
npx playwright install chromium
```

Backend'i ayrı terminalde 8000 portunda başlatın, ardından `npm run test:ui` çalıştırın. Testler model yükleme hatasını, yeniden denemeyi, iptali, yeni sohbeti, cihazdaki kaydı ve mobil taşmayı kontrol eder. Tarayıcı testinde de API cevapları taklit edilir.

Gerçek cihazdaki son kontrol: Ollama açıkken modeli seçin; normal bir soru sorun; GitHub araması yaptırın; sonra Ollama'yı kapatıp uygulamanın anlaşılır hata gösterdiğini doğrulayın.

Bu uygulamanın varsayılan çalıştırma adresi yalnızca yerel bilgisayardır. Kullanıcı hesabı ve internet üzerinden çok kullanıcılı erişim bu değişikliğin kapsamında değildir.
