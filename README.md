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
- Tracks a virtual paper trading portfolio, separately per market — either
  by hand (manual Buy/Sell against live prices) or fully automated
  (AutoTrader's own N-day simulation, running independently).

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
özeti, manuel Al/Sat işlemi), pozisyon büyüklüğü hesaplayıcı ve her piyasa
için ayrı, gerçekten tıklanabilir bir kağıt portföy (pozisyonlar, canlı
gerçekleşmemiş K/Z, işlem geçmişi) — hepsi Türkçe ve 5 saniyede bir otomatik
yenilenir. Tamamen istemci
tarafı; harici bir kütüphane gerektirmez (sadece `/docs` Swagger sayfası CDN
kullanır; BIST sekmesi ve haberler Yahoo Finance'e erişim gerektirir). Bu
dashboard, PyInstaller ile paketlenen `AlphaScope.exe` içine de otomatik
olarak dahil edilir.

## Global (ABD), BIST 30 ve Kripto sekmeleri

`MarketContext` mimarisi sayesinde her piyasa diğerinden tamamen bağımsız bir
"piyasa" olarak çalışır — kendi provider'ı, kendi tarayıcı durumu ve kendi
kağıt portföyü (Global/Kripto: $, BIST: ₺) vardır; biri çökse/yavaşlasa
diğerini etkilemez. Üçü de **aynı gerçek veri kaynağını** kullanır: Yahoo
Finance (`yfinance` paketi, `YFinanceProvider`,
`app/market_data/providers/yfinance_provider.py`), API anahtarı gerekmez —
kripto için de ayrı bir borsa entegrasyonu (ccxt vb.) yok, yfinance zaten
`BTC-USD` gibi `-USD` uzantılı kripto sembollerini destekliyor.

- **⚠️ Önemli — gecikme:** Yahoo Finance verisi genellikle **~15-20 dakika
  gecikmelidir** ve bir aracı kurumun/borsanın gerçek zamanlı emir akışının
  yerini tutmaz. Dashboard'da her sekmenin üstünde bu uyarı her zaman görünür.
  Gerçek yatırım kararı vermeden önce fiyatı aracı kurumunuzdan/borsanızdan
  mutlaka teyit edin.
- **Global (ABD):** Semboller uzantısız sorgulanır (örn. `AAPL`). Sembol
  listesi: `.env` içindeki `GLOBAL_SYMBOLS` — varsayılan olarak teknoloji,
  finans, sağlık, tüketim, enerji, telekom ve sanayi sektörlerine yayılmış
  ~50 büyük/likit ABD şirketi (AAPL, MSFT, JPM, JNJ, WMT, XOM gibi). Sorgu
  sıklığı: `GLOBAL_POLL_INTERVAL_SECONDS` (varsayılan 60sn).
- **BIST 30:** Semboller `.IS` uzantısıyla sorgulanır (örn. `THYAO.IS`) ama
  sistemde ve arayüzde uzantısız gösterilir (`THYAO`). Sembol listesi: `.env`
  içindeki `BIST_SYMBOLS` — varsayılan olarak 30 büyük/likit BIST hissesi
  gelir, ancak bu **resmi BIST 30 endeks bileşenleri ile birebir aynı
  olmayabilir** (endeks üyeliği periyodik değişir). Sorgu sıklığı:
  `BIST_POLL_INTERVAL_SECONDS` (varsayılan 60sn). BIST sekmesini tamamen
  kapatmak isterseniz `.env`'de `BIST_ENABLED=false`.
- **Kripto:** Semboller `-USD` uzantısıyla sorgulanır (örn. `BTC-USD`) ama
  arayüzde uzantısız gösterilir (`BTC`). Sembol listesi: `.env` içindeki
  `CRYPTO_SYMBOLS` — varsayılan olarak 8 büyük kripto para (BTC, ETH, BNB,
  SOL, XRP, ADA, DOGE, AVAX). Sorgu sıklığı: `CRYPTO_POLL_INTERVAL_SECONDS`
  (varsayılan 60sn). Kripto piyasası 7/24 açık olduğu için, diğer iki
  sekmenin aksine **"piyasa kapalı" bir mazeret değildir** — veri uzun süre
  eskirse (bkz. Veri tazeliği aşağıda) bu bir aksama işareti olabilir. Temel
  analiz (F/K, kâr marjı vb.) kripto için anlamsız olduğundan bu sekmede
  gösterilmez. Kapatmak isterseniz `.env`'de `CRYPTO_ENABLED=false`.
  İsteğe bağlı: `CRYPTO_MARKET_DATA_PROVIDER=binance` ile Yahoo Finance'in
  60sn'lik gecikmeli polling'i yerine Binance'in ücretsiz, kimlik doğrulama
  gerektirmeyen WebSocket akışına (gerçek zamanlı, gecikmesiz) geçilebilir —
  varsayılan `yfinance` kalır, hiçbir şey değişmez.
- Farklı sembol takip etmek için ilgili `.env` değişkenindeki virgülle
  ayrılmış listeyi düzenlemeniz yeterli, kod değişikliği gerekmez.
- Veri zaten gecikmeli olduğundan sorgu aralığını çok düşürmenin faydası
  yoktur; gereksiz sorgu Yahoo tarafından geçici olarak sınırlanmanıza
  (rate limit) yol açabilir.
- **Bar birikimi:** Her sekme de EMA200 gibi uzun pencereli göstergeler
  için canlı piyasa saatlerinde biriken ~200 bar'a ihtiyaç duyar (bkz.
  `bars_available` alanı, sembol detayında gösterilir). Piyasa kapalıyken
  (örn. ABD borsası kapandığında Global için, ya da gece BIST için) yeni bar
  gelmez — bu bir hata değildir, normaldir (Kripto hariç: o piyasa hiç kapanmaz).
  Bu birikim `app/scanner/db_models.py`
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
- `dip_opportunity` — trend-takip Fırsat Skoru'ndan **tamamen ayrı**, RSI aşırı
  satım + alt Bollinger bandına yakınlık + hacim onayına dayalı bir tepki-alımı
  (mean-reversion) okuması — `app/signals/dip_detector.py`. Kasıtlı olarak
  ana skora karıştırılmaz: bir sembol trend kurallarına göre `AVOID` olurken
  aynı anda burada bir dip adayı olarak işaretlenebilir; bu bir çelişki değil,
  iki farklı stratejinin (trend takibi vs. tepki alımı) doğal olarak farklı
  şeyler görmesidir. Güven seviyesi (`confidence`: `STRONG`/`MEDIUM`/`WEAK`)
  hacim onayının gücüne göre belirlenir.

## Sinyal performansı (kendi geçmişinden öğrenme)

`scoring.py`'deki kurallar (RSI 45-65 "sağlıklı", EMA sıralaması vb.) genel
kabul görmüş teknik analiz kalıpları ama hiçbir zaman geriye dönük olarak
doğrulanmadı — sistem "STRONG_BUY_SETUP dediğim semboller gerçekten daha
iyi performans gösteriyor mu?" sorusuna cevap veremiyordu. Bunu çözmek için:

- Bir sembolün sinyali **değiştiği** her anda (aynı sinyal sürdüğü sürece
  değil, sadece gerçek bir değişimde) bu an, o anki fiyatla birlikte
  kaydedilir — `app/signals/tracking_repository.py`.
- 5, 10 ve 20 gün sonra (`app/signals/signal_tracking_service.py`, saatlik
  kontrol), o kayıt için güncel fiyat bulunup getiri % hesaplanır.
- Dashboard'daki **Sinyal Performansı** paneli, her sinyal tipi × süre için
  ortalama getiriyi gösterir — ama **en az 3 örneği** olmayan kombinasyonlar
  hiç gösterilmez (tek bir gözlemi "istatistik" gibi sunmamak için).
- Bu, backtesting değildir (geçmişe gitmez, sadece ileri doğru gerçek
  veriyle birikir) — bunun için bkz. "Backtest" bölümü aşağıda.
- `GET /api/{market}/signal-performance` uç noktasından da okunabilir.
  **Geçmiş performans gelecekteki sonuçları garanti etmez; bu bir yatırım
  tavsiyesi değildir.**

## Backtest (geriye dönük test)

Sinyal performansı takibi (yukarıda) haftalar/aylar süren bir veri
birikimi gerektiriyor — "bugünkü kural seti kâr getirir miydi?" sorusuna
dakikalar içinde bir tahmin vermek için `app/backtest/` bugünkü canlı
kod yolunu (`ScannerEngine`, `SignalEngine`, `RiskEngine`, `dip_detector`,
`PaperPortfolio` — hepsi saf, DB'den habersiz) geçmiş **günlük** barlarla
besleyip aynı giriş/çıkış kurallarını (sektör hariç — bkz. aşağı) replay
eder. Dashboard'daki **Backtest** panelinden ("Backtest Çalıştır") 1/2/3/5
yıllık bir dönem seçilip çalıştırılabilir; sonuçta toplam getiri, aynı
dönemde piyasa endeksini (Global: S&P 500, BIST: BIST 100, Kripto: BTC)
sadece alıp tutmanın getirisiyle karşılaştırma, kazanma oranı, ortalama
kazanç/kayıp %, maksimum düşüş, basit Sharpe oranı ve bir equity eğrisi
gösterilir.

**Bilinçli sınırlamalar** (sonuçta da belirtilir):
- yfinance'in dakikalık verisi ~7 gün geriye gidiyor, çok yıllık bir
  backtest için tek seçenek **günlük** bar — EMA200 artık "200 dakika"
  değil, klasik "200 gün" anlamına geliyor (canlı sistemden daha anlamlı
  bir okuma), ama VWAP günlük barda o günün ortalama fiyatına dejenere olur.
- Sektör çeşitlendirme, Uzun Vadeli Görünüm ve haber duyarlılığı filtreleri
  **backtest'te yok** — geçmişe dönük nokta-zamanlı temel veri (3 yıl önceki
  F/K gibi) ya da haber arşivi ücretsiz olarak mevcut değil; bugünün
  verisini geçmişe uygulamak veri sızıntısı olurdu, o yüzden hiç uygulanmıyor.
- Günlük trend onayı backtest'te ayrıca hesaplanmıyor — zaten günlük bar
  kullanıldığı için ana trend skoruyla aynı şeyi tekrar eder.
- VIX bazlı risk küçültme, dip girişleri, zarar tavanı, kısmi kâr alma ve
  işlem maliyeti ise tam sadakatle replay edilir.
- `POST /api/{market}/backtest/run` — sonuçlar kalıcı değil, her çağrı
  yeniden hesaplar. **Geçmiş performans gelecekteki sonuçları garanti
  etmez; bu bir yatırım tavsiyesi değildir.**

## API endpoints

Tüm tarayıcı/sinyal/haber/portföy uç noktaları `{market}` parametresi alır
(`global`, `bist` veya `crypto`):

- `GET /health` — liveness check.
- `GET /api/markets` — mevcut piyasaların listesi (anahtar, etiket, para birimi, not).
- `GET /api/{market}/symbols` — o piyasanın takip ettiği semboller.
- `GET /api/{market}/scanner` — tarayıcı sonuçları (`?min_score=`, `?signal=`).
- `GET /api/{market}/signals/{symbol}` — skor kırılımı, gerekçeler, risk analizi, alım bölgesi.
- `GET /api/{market}/news/{symbol}` — haber başlıkları + duyarlılık özeti.
- `GET /api/{market}/fundamentals/{symbol}` — uzun vadeli görünüm (temel analiz).
- `GET /api/{market}/macro` — makro göstergeler (USD/TRY, BIST 100, S&P 500, VIX).
- `GET /api/{market}/portfolio` — o piyasanın kağıt portföy durumu (pozisyonlar, canlı K/Z, işlem geçmişi).
- `POST /api/{market}/portfolio/buy`, `POST /api/{market}/portfolio/sell` — manuel kağıt alım/satım (`{symbol, quantity}`; fiyat her zaman sunucu tarafında canlı sinyalden çözülür).
- `GET /api/{market}/simulation/status`, `POST /api/{market}/simulation/start` — N günlük otomatik simülasyon.
- `POST /api/{market}/backtest/run` — geriye dönük test (`{years, initial_cash}`), bkz. "Backtest" bölümü.
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
- `GLOBAL_SYMBOLS`, `GLOBAL_POLL_INTERVAL_SECONDS` — see "Global (ABD), BIST 30 ve Kripto sekmeleri" above.
- `BIST_ENABLED`, `BIST_SYMBOLS`, `BIST_POLL_INTERVAL_SECONDS` — see "Global (ABD), BIST 30 ve Kripto sekmeleri" above.
- `CRYPTO_ENABLED`, `CRYPTO_SYMBOLS`, `CRYPTO_POLL_INTERVAL_SECONDS` — see "Global (ABD), BIST 30 ve Kripto sekmeleri" above.
- `CRYPTO_MARKET_DATA_PROVIDER=yfinance` (default) — set to `binance` to switch
  the crypto tab to Binance's free public WebSocket for real-time data instead
  of polled/delayed Yahoo Finance. No API key needed. `BINANCE_QUOTE_ASSET=USDT`
  (default) controls which pair `CRYPTO_SYMBOLS` entries are matched against
  (e.g. "BTC" → "BTCUSDT").
- `NEWS_ENABLED`, `NEWS_POLL_INTERVAL_SECONDS`, `NEWS_MAX_ITEMS_PER_SYMBOL` — see "Haber duyarlılığı" above.
- `ACCESS_PASSWORD` — unset by default, which leaves every `/api/*` route open
  (correct for the desktop build: it only ever listens on 127.0.0.1). Set this
  on a web deploy (Render, etc.) to require it before the dashboard will show
  any data — see `app/auth/session.py` for how the resulting cookie is signed
  and app.js's login overlay for the frontend side. Rotating this value logs
  out every existing session at once.

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
  Never scores a symbol, but VIX is read by `app/autotrader/` to derate new
  position sizing when market-wide risk appetite is low.
- `app/daily_trend/` — daily-bar (EMA50/EMA200) trend direction per symbol,
  polled far less often than intraday bars. Used only as an AutoTrader entry
  gate (see below), not by the short-term Opportunity Score.
- `app/autotrader/` — self-driving N-day paper trading simulation, persisted
  to SQLite (`app/autotrader/db_models.py`) so a run survives a restart.
  Entry uses `AUTOTRADER_ENTRY_SCORE_MIN`, AutoTrader's own score bar —
  deliberately looser than, and independent from, the dashboard's
  STRONG_BUY_SETUP/BUY_SETUP labels (`signal_engine.py`'s 75/85). A
  backtest found the display's bar so strict AutoTrader sat in ~96% cash;
  a calibration sweep (`app/backtest/`) against real Global (3y) + BIST
  (2y) history picked 60. Exit on AVOID also no longer fires on a single
  reading — it requires `AVOID_EXIT_STREAK_REQUIRED` (3, same sweep)
  consecutive checks, since a lone reading was whipsawing positions out on
  routine noise. Position sizing is risk-based (`RISK_PER_TRADE_FRACTION` of cash risked to
  the stop distance, capped by `MAX_POSITION_ALLOCATION_FRACTION`) rather
  than a flat percentage — a volatile/wide-stop symbol gets a smaller
  position than a calm one for the same dollar risk. The stop-loss trails up
  (ATR distance from the current price) as a position gains, never back
  down, to lock in gains instead of giving back a whole reversal — visible
  in the dashboard's simulation panel as "Zarar-Kes (İz Süren)". At most
  `MAX_POSITIONS_PER_SECTOR` open positions may share the same
  fundamentals sector, forcing real diversification. A second entry path
  opens on a STRONG `DipOpportunity` even without a trend-following buy
  setup (trade-logged separately as "Dip Fırsatı"). Both entry paths require
  the daily-bar trend (`app/daily_trend/`, EMA50 vs EMA200) not to be
  confirmed down, and new-position risk is derated when VIX is elevated —
  none of this touches the Opportunity Score itself, only which symbols the
  simulation actually buys and how large those positions are. Both entry
  paths also skip a symbol whose long-term fundamentals outlook (see
  "Uzun vadeli görünüm" below) is confirmed UNFAVORABLE, and likewise skip
  one whose recent news sentiment reads a confirmed NEGATIVE once its
  cached headlines are filtered down to ones that actually name the
  company (`app/news/relevance.py`, `app/news/symbol_aliases.py`) and
  there are enough of them to trust the reading. A portfolio-level
  circuit breaker pauses new entries (existing positions keep exiting
  normally) once a run's equity has drawn down `MAX_DRAWDOWN_FRACTION`
  from its peak — visible in the simulation panel as "Zirve Özkaynak".
  BIST and Crypto both get a wider `HIGH_VOLATILITY_MAX_DRAWDOWN_FRACTION`
  (20% vs. the default 10%): separate 3y backtest sweeps found the flat
  threshold paused new entries on 64% of BIST's trading days and 70% of
  Crypto's (vs. 0% for Global) because both realize much higher volatility
  than Global — see `max_drawdown_fraction_for_market()`.
  Take-profit fires in two steps: half the position closes at TP1, the
  remainder's target is promoted to TP2 with its stop still trailing
  ("Kısmi Kâr Alım" in the trade log). A flat `TRANSACTION_COST_RATE` is
  charged on both legs of every trade so reported returns aren't an
  unrealistic zero-friction number. `app/storage/database.py`'s
  `ensure_columns()` is what lets these new SQLite columns land on a
  simulation that was already running before the upgrade, without losing
  its history — `create_all()` alone only creates brand-new tables.
- `app/backtest/` — replays the live scoring/entry/exit rules against
  historical daily bars (see "Backtest" above for what's faithfully
  replayed vs. deliberately omitted). Reuses ScannerEngine/SignalEngine/
  RiskEngine/PaperPortfolio directly rather than a separate
  reimplementation, so it tests the actual rules.
- `app/portfolio/` — virtual paper trading only. `PaperPortfolio` is a pure,
  DB-unaware buy()/sell() engine (same shape as `ScannerEngine`); persistence
  is bolted on separately via `portfolio_repository.py`
  (mirrors `bar_repository.py`'s plain-function style) so a manual position
  survives a restart. Fully independent from AutoTrader, which keeps its
  own positions in `simulation_positions` — the two never interact beyond
  reading the same live price stream.
- `app/services/` — background tasks wiring the provider stream into the scanner,
  with reconnect/backoff so a provider outage never crashes the app.
- `app/notifications/` — desktop-build-only Windows toast notifications for a
  new AutoTrader position or a drawdown-breaker pause. `NullNotifier` on the
  web deploy and whenever `NOTIFICATIONS_ENABLED=false`; `AutoTraderService`
  always has a notifier to call either way, never branches on which.
- `app/auth/` — a single shared-password gate for the web deploy (see
  "Configuration" above, `ACCESS_PASSWORD`), not a multi-user accounts
  system — AlphaScope has no per-user concept. A stateless, signed cookie
  (`session.py`) rather than server-side session storage.

## Tests

```bash
pytest
```

Covers indicator math, signal classification boundaries (including negative/opposing
reasons and the buy-zone calculation), risk/position sizing, mock provider behavior
(determinism, lifecycle, event normalization), and the BIST provider's Yahoo Finance
response parsing (mocked, no live network calls in tests).
