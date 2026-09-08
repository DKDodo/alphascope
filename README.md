---
title: AlphaScope
emoji: 📈
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# AlphaScope

Real-time global market scanner and trading **decision-support** system.

**No live trading.** This codebase contains no real order-execution path.
Only market data, technical analysis, scanning, news sentiment, and paper
(virtual) trading are implemented. `LIVE_TRADING_ENABLED` is forced to
`false` and rejected at startup if anyone tries to flip it on.

## What it does

```
Market Data (Global + BIST, both Yahoo Finance) -> Normalizer -> Scanner -> Indicators -> Signal Engine -> Risk Engine -> FastAPI -> Dashboard
                                                                          -> News Provider -> FinBERT Sentiment ->
```

- Streams real, Yahoo-delayed market data for both Global (ABD) and BIST 30 as two independent tabs.
- Computes EMA9/20/50/200, RSI14, MACD, ATR14, Bollinger Bands, VWAP, volume ratio, momentum.
- Scores each symbol 0-100 (Opportunity Score) across Trend/Momentum/Volume/Price Action/Risk-Reward.
- Classifies a signal: `STRONG_BUY_SETUP`, `BUY_SETUP`, `WATCH`, `NEUTRAL`, `AVOID`.
- Explains **both directions**: every score comes with the specific factors that pushed it up
  *and* the ones working against it (e.g. why something is `AVOID`, not just why it isn't `BUY`).
- Computes ATR-based stop-loss/take-profit ("sell" price floors) and a
  Bollinger/ATR-based reference pullback zone ("buy" price floor).
- Fetches per-symbol news headlines and scores them locally with FinBERT (no API key, no data leaves the machine).
- Tracks a virtual paper trading portfolio, separately per market.

None of this is investment advice.

## Running on Windows (from scratch)

1. Install Python 3.12+ from [python.org](https://www.python.org/downloads/) (check "Add to PATH").
2. Open a terminal in this folder and create a virtual environment:

```bash
python -m venv .venv
```

3. Activate it:

```bash
.venv\Scripts\activate
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Copy the example environment file:

```bash
copy .env.example .env
```

6. Start the server:

```bash
uvicorn app.main:app --reload
```

7. Open your browser at **http://127.0.0.1:8000/** for the Turkish dashboard
   (or **http://127.0.0.1:8000/docs** for the interactive Swagger UI).

Or just double-click **`run.bat`**, which does all of the above automatically.

### One-click desktop app

Run `build_exe.bat` once (from an activated venv with dependencies installed)
to produce `dist/AlphaScope.exe` via PyInstaller — a single file that starts
the server and shows the dashboard in its own native window (no browser tab),
no Python installation required on the target machine. See [PACKAGING.md](PACKAGING.md) for details and how to put
a shortcut on the Desktop.

## Dashboard (Türkçe arayüz)

`http://127.0.0.1:8000/` bağımsız bir web dashboard'u açar (`app/web/`):
sekmeli piyasa görünümü (**Global (ABD)** ve **BIST 30**), tarayıcı
sonuçları, sembol detayı (skor kırılımı, hem olumlu hem olumsuz gerekçeler,
risk analizi, alım için referans fiyat bölgesi, son haberler ve duyarlılık
özeti), pozisyon büyüklüğü hesaplayıcı ve her piyasa için ayrı kağıt portföy
özeti — hepsi Türkçe ve 5 saniyede bir otomatik yenilenir. Tamamen istemci
tarafı; harici bir kütüphane gerektirmez (sadece `/docs` Swagger sayfası CDN
kullanır; BIST sekmesi ve haberler Yahoo Finance'e erişim gerektirir). Bu
dashboard, PyInstaller ile paketlenen `AlphaScope.exe` içine de otomatik
olarak dahil edilir.

## Global (ABD) ve BIST 30 sekmeleri

`MarketContext` mimarisi sayesinde her piyasa diğerinden tamamen bağımsız bir
"piyasa" olarak çalışır — kendi provider'ı, kendi tarayıcı durumu ve kendi
kağıt portföyü (Global: $, BIST: ₺) vardır; biri çökse/yavaşlasa diğerini
etkilemez. Her iki sekme de **aynı gerçek veri kaynağını** kullanır:
Yahoo Finance (`yfinance` paketi, `YFinanceProvider`,
`app/market_data/providers/yfinance_provider.py`), API anahtarı gerekmez.

- **⚠️ Önemli — gecikme:** Yahoo Finance verisi genellikle **~15-20 dakika
  gecikmelidir** ve bir aracı kurumun gerçek zamanlı emir akışının yerini
  tutmaz. Dashboard'da her iki sekmenin üstünde bu uyarı her zaman görünür.
  Gerçek yatırım kararı vermeden önce fiyatı aracı kurumunuzdan mutlaka teyit edin.
- **Global (ABD):** Semboller uzantısız sorgulanır (örn. `AAPL`). Sembol
  listesi: `.env` içindeki `GLOBAL_SYMBOLS` — varsayılan olarak 8 büyük ABD
  hissesi (AAPL, MSFT, NVDA, AMD, META, TSLA, AMZN, GOOGL). Sorgu sıklığı:
  `GLOBAL_POLL_INTERVAL_SECONDS` (varsayılan 60sn).
- **BIST 30:** Semboller `.IS` uzantısıyla sorgulanır (örn. `THYAO.IS`) ama
  sistemde ve arayüzde uzantısız gösterilir (`THYAO`). Sembol listesi: `.env`
  içindeki `BIST_SYMBOLS` — varsayılan olarak 30 büyük/likit BIST hissesi
  gelir, ancak bu **resmi BIST 30 endeks bileşenleri ile birebir aynı
  olmayabilir** (endeks üyeliği periyodik değişir). Sorgu sıklığı:
  `BIST_POLL_INTERVAL_SECONDS` (varsayılan 60sn). BIST sekmesini tamamen
  kapatmak isterseniz `.env`'de `BIST_ENABLED=false`.
- Farklı hisse takip etmek için ilgili `.env` değişkenindeki virgülle ayrılmış
  listeyi düzenlemeniz yeterli, kod değişikliği gerekmez.
- Veri zaten gecikmeli olduğundan sorgu aralığını çok düşürmenin faydası
  yoktur; gereksiz sorgu Yahoo tarafından geçici olarak sınırlanmanıza
  (rate limit) yol açabilir.
- **Bar birikimi:** Her iki sekme de EMA200 gibi uzun pencereli göstergeler
  için canlı piyasa saatlerinde biriken ~200 bar'a ihtiyaç duyar (bkz.
  `bars_available` alanı, sembol detayında gösterilir). Piyasa kapalıyken
  (örn. ABD borsası kapandığında Global için, ya da gece BIST için) yeni bar
  gelmez — bu bir hata değildir, normaldir. Bu birikim `app/scanner/db_models.py`
  üzerinden veritabanına kalıcı olarak yazılır (`app/scanner/bar_repository.py`),
  bu yüzden bir yeniden başlatma (redeploy, masaüstü EXE'nin kapatılıp
  açılması) sonrasında **sıfırdan başlamaz** — kaldığı yerden devam eder.
- **Veri tazeliği:** Her sinyal, kullanılan son bar'ın yaşını (`data_age_seconds`)
  taşır. Sembol detayında, bu yaş ~30 dakikayı aşarsa bir uyarı gösterilir —
  genellikle piyasanın kapalı olmasından kaynaklanır (gece, hafta sonu, tatil),
  ama piyasa açıkken uzun süre böyle kalırsa veri akışında bir aksama olabileceğine
  işaret eder — bkz. `app/signals/signal_engine.py`'deki `_compute_data_age`.

## Haber duyarlılığı (news sentiment)

Her sembol için Yahoo Finance'ten (yfinance üzerinden) son haber
başlıkları çekilir ve **FinBERT** (finans metinlerine özel eğitilmiş, açık
kaynak bir dil modeli) ile yerel olarak — hiçbir veri dışarı gönderilmeden —
olumlu/olumsuz/nötr olarak sınıflandırılır.

- **Kapsam:** "Tüm haber siteleri" taranmaz — bu hem teknik hem hukuki olarak
  (çoğu sitenin kullanım koşulları scraping'i yasaklar) gerçekçi değil.
  Yahoo Finance, hem Global hem BIST sembolleri için tek, güvenilir ve
  API-key gerektirmeyen bir kaynak olduğu için seçildi.
- **Sınıflandırma sınırları:** FinBERT istatistiksel bir modeldir, gerçek
  olayları doğrulamaz ve bağlamı bazen kaçırabilir. Her haber özetinde bu
  uyarı açıkça gösterilir; kaynak haberi mutlaka kendiniz okuyun.
- **İlk çalıştırma:** Model (~500MB) Hugging Face'ten indirilir ve yerel
  önbelleğe (`~/.cache/huggingface`) kaydedilir; sonraki çalıştırmalar
  internet olmadan da modeli kullanabilir (haber çekmek için yine internet gerekir).
- **Devre dışı bırakma / zarif düşüş:** `torch`/`transformers` kurulu değilse
  ya da model yüklenemezse (web deploy'u bunları boyut/RAM nedeniyle içermiyor,
  bkz. `requirements-web.txt`), sistem otomatik olarak hafif, anahtar kelime
  tabanlı bir sınıflandırıcıya düşer (`app/news/keyword_sentiment.py`) — haber
  başlıkları her koşulda gösterilir, hangi yöntemin kullanıldığı
  (`sentiment_method: "finbert" | "keyword"`) API yanıtında ve arayüzde
  açıkça belirtilir, biri diğeriyle karıştırılmaz. Tamamen kapatmak için
  `.env`'de `NEWS_ENABLED=false`.
- **Sorgu sıklığı:** `NEWS_POLL_INTERVAL_SECONDS` (varsayılan 900sn/15dk) —
  haberler dakikada bir değişmediği için sık sorgulamaya gerek yok.

## Uzun vadeli görünüm (temel analiz) ve makro bağlam

Her sembol detayında, kısa vadeli teknik sinyalden tamamen ayrı olarak:

- **Uzun Vadeli Görünüm**: F/K oranı, F/DD (Piyasa Değeri/Defter Değeri)
  oranı, net kâr marjı, FAVÖK marjı, gelir büyümesi, ROE, borç/özkaynak
  oranı, analist konsensüsü ve uzun vadeli trend (EMA50 vs EMA200) —
  `app/fundamentals/`, skora dahil edilir (0-100). Ayrıca piyasa değeri,
  defter değeri (hisse başına) ve net kâr tutarı bilgi amaçlı gösterilir
  ama **kasıtlı olarak skorlanmaz** — bunlar şirket büyüklüğüne göre doğal
  olarak değiştiği için "yüksek/düşük = iyi/kötü" diye bir kural yok (aynı
  mantık `current_price`/`analyst_target_price` için de geçerli). Uzun
  Vadeli Görünüm, kısa vadeli Fırsat Skoru ile de **kasıtlı olarak
  birleştirilmez**: bir hisse kısa vadede iyi bir teknik kurulum, uzun
  vadede zayıf bir temel hikâye olabilir (ya da tam tersi).
- **Makro şerit** (sekmelerin altında): BIST'te USD/TRY ve BIST 100, Global'de
  S&P 500 ve VIX — `app/macro/`. Sadece bilgi amaçlı, hiçbir skora karışmaz.

**⚠️ Bilinen kısıtlama (web deploy'unda):** Uzun Vadeli Görünüm verisi
Yahoo Finance'in `quoteSummary` uç noktasından geliyor; gözlemlediğimiz
kadarıyla bu uç nokta bazı bulut barındırma IP'lerini (Render dahil)
engelliyor — fiyat/tarama/makro verisinin geldiği `chart`/`download` uç
noktası engellenmiyor. Sonuç: web sürümünde Uzun Vadeli Görünüm çalışmayabilir
(arayüzde bunu açıkça belirtiriz — bkz. `likely_blocked` alanı), **masaüstü
sürümünde ise sorunsuz çalışır**. Kalıcı bir çözüm için API-key'li ücretli
bir veri kaynağına geçmek gerekir.

## Gerekçeler ve fiyat seviyeleri

Her sinyal, sadece "kaç puan" değil **neden** o puanı aldığını gösterir:

- `reasons` listesindeki her madde `positive: true/false` taşır — bir
  `AVOID` sinyali de en az bir `STRONG_BUY_SETUP` kadar açıklanabilir
  (örn. "RSI aşırı satım bölgesinde", "Fiyat VWAP altında — zayıf fiyat aksiyonu").
- `risk_analysis.stop_loss` / `take_profit_1` / `take_profit_2` — **satış**
  tarafı için ATR bazlı fiyat tabanları.
- `buy_zone_low` / `buy_zone_high` — **alım** tarafı için referans bir
  geri çekilme bölgesi (Bollinger orta bandı ile bir ATR altı arası). Bu bir
  garanti değil, mevcut volatiliteye göre hesaplanan istatistiksel bir
  referanstır.

## API endpoints

Tüm tarayıcı/sinyal/haber/portföy uç noktaları `{market}` parametresi alır
(`global` veya `bist`):

- `GET /health` — liveness check.
- `GET /api/markets` — mevcut piyasaların listesi (anahtar, etiket, para birimi, not).
- `GET /api/{market}/symbols` — o piyasanın takip ettiği semboller.
- `GET /api/{market}/scanner` — tarayıcı sonuçları (`?min_score=`, `?signal=`).
- `GET /api/{market}/signals/{symbol}` — skor kırılımı, gerekçeler, risk analizi, alım bölgesi.
- `GET /api/{market}/news/{symbol}` — haber başlıkları + duyarlılık özeti.
- `GET /api/{market}/fundamentals/{symbol}` — uzun vadeli görünüm (temel analiz).
- `GET /api/{market}/macro` — makro göstergeler (USD/TRY, BIST 100, S&P 500, VIX).
- `GET /api/{market}/portfolio` — o piyasanın kağıt portföy durumu.
- `GET /api/{market}/simulation/status`, `POST /api/{market}/simulation/start` — N günlük otomatik simülasyon.
- `POST /api/risk/position-size` — hesap bakiyesi/risk yüzdesi/giriş/stop'tan pozisyon büyüklüğü.

Örnek: `GET /api/bist/scanner`, `GET /api/global/signals/AAPL`, `GET /api/bist/news/THYAO`.

## Configuration (`.env`)

See `.env.example`. Key settings:

- `MARKET_DATA_PROVIDER=yfinance` (default) — real, delayed Yahoo Finance data
  for both tabs, zero API keys. Set to `mock` for synthetic random-walk data
  (offline dev/testing) or `massive` + `MASSIVE_API_KEY` for the (skeleton)
  Massive WebSocket provider; `massive` falls back to `yfinance` if the key is missing.
- `DATABASE_URL=sqlite:///./alphascope.db` — no database server required. Point
  this at Postgres in production without any code changes.
- `PAPER_TRADING_ONLY=true`, `LIVE_TRADING_ENABLED=false` — must stay this way.
- `GLOBAL_SYMBOLS`, `GLOBAL_POLL_INTERVAL_SECONDS` — see "Global (ABD) ve BIST 30 sekmeleri" above.
- `BIST_ENABLED`, `BIST_SYMBOLS`, `BIST_POLL_INTERVAL_SECONDS` — see "Global (ABD) ve BIST 30 sekmeleri" above.
- `NEWS_ENABLED`, `NEWS_POLL_INTERVAL_SECONDS`, `NEWS_MAX_ITEMS_PER_SYMBOL` — see "Haber duyarlılığı" above.

## Architecture

- `app/market_data/base.py` — `BaseMarketDataProvider` interface every provider implements
  (yfinance for both Global and BIST, mock, Massive, and future Alpaca/Binance/IBKR providers).
- `app/services/market_context.py` — bundles one market's universe + provider +
  scanner + news service + paper portfolio; `app/main.py` builds one context per tab
  (`global`, `bist`) so they run and fail independently of each other.
- `app/market_data/normalizer.py` — converts provider-native payloads into the
  shared `MarketEvent` model before anything downstream sees them.
- `app/scanner/scanner_engine.py` — rolling per-symbol OHLCV state + indicator computation.
- `app/signals/` — scoring rules (with both supporting and opposing reasons) and signal classification.
- `app/risk/` — ATR-based stop/target and position sizing.
- `app/news/` — Yahoo Finance headline fetching + FinBERT sentiment scoring
  (falls back to `keyword_sentiment.py` when torch/transformers aren't installed).
- `app/fundamentals/` — long-term outlook: company fundamentals + long-term
  trend, scored separately from the short-term signal.
- `app/macro/` — informational macro indicators (FX pairs, market indices).
- `app/autotrader/` — self-driving N-day paper trading simulation, persisted
  to SQLite (`app/autotrader/db_models.py`) so a run survives a restart.
- `app/portfolio/` — virtual paper trading only.
- `app/services/` — background tasks wiring the provider stream into the scanner,
  with reconnect/backoff so a provider outage never crashes the app.

## Tests

```bash
pytest
```

Covers indicator math, signal classification boundaries (including negative/opposing
reasons and the buy-zone calculation), risk/position sizing, mock provider behavior
(determinism, lifecycle, event normalization), and the BIST provider's Yahoo Finance
response parsing (mocked, no live network calls in tests).
