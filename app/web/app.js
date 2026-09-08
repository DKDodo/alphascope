const SINYAL_ETIKET = {
  STRONG_BUY_SETUP: "Güçlü Alım Fırsatı",
  BUY_SETUP: "Alım Fırsatı",
  WATCH: "İzlemede",
  NEUTRAL: "Nötr",
  AVOID: "Kaçının",
};

const RISK_ETIKET = { LOW: "Düşük", MEDIUM: "Orta", HIGH: "Yüksek" };

const DIP_GUVEN_ETIKET = { STRONG: "Güçlü", MEDIUM: "Orta", WEAK: "Zayıf" };
const DIP_GUVEN_BADGE_SINIF = { STRONG: "STRONG_BUY_SETUP", MEDIUM: "NEUTRAL", WEAK: "NEUTRAL" };

const KATEGORI_ETIKET = {
  trend: "Trend",
  momentum: "Momentum",
  volume: "Hacim",
  price_action: "Fiyat Hareketi",
  risk_reward: "Risk / Ödül",
};

const RISK_ALAN_ETIKET = {
  entry_price: "Giriş Fiyatı",
  stop_loss: "Zarar Kes (Stop)",
  take_profit_1: "Kâr Al 1 (TP1)",
  take_profit_2: "Kâr Al 2 (TP2)",
  atr: "ATR (Ort. Gerçek Aralık)",
  risk_per_share: "Pay Başına Risk",
  reward_per_share_tp1: "Pay Başına Ödül (TP1)",
  risk_reward_ratio: "Risk / Ödül Oranı",
};

let pazarlar = [];
let aktifPazar = null;
let secilenSembol = null;

function aktifPazarBilgi() {
  return pazarlar.find((p) => p.key === aktifPazar) || { currency_symbol: "" };
}

function paraFormat(deger) {
  if (deger === null || deger === undefined || Number.isNaN(deger)) return "-";
  return deger.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function paraBirimli(deger) {
  return `${paraFormat(deger)} ${aktifPazarBilgi().currency_symbol}`.trim();
}

function skorRengi(skor) {
  if (skor >= 75) return "#2ecc71";
  if (skor >= 65) return "#8fd14f";
  if (skor >= 40) return "#f1c40f";
  return "#e74c3c";
}

async function veriCek(yol, secenekler) {
  const yanit = await fetch(yol, secenekler);
  if (!yanit.ok) {
    const govde = await yanit.json().catch(() => ({}));
    throw new Error(govde.detail || `İstek başarısız (${yanit.status})`);
  }
  return yanit.json();
}

function durumGuncelle(baglandi) {
  const el = document.getElementById("baglanti-durumu");
  el.className = "status " + (baglandi ? "baglandi" : "hata");
  el.querySelector("span:last-child").textContent = baglandi ? "Bağlı" : "Bağlantı hatası";
}

async function pazarlariYukle() {
  pazarlar = await veriCek("/api/markets");
  if (!aktifPazar && pazarlar.length) {
    aktifPazar = pazarlar[0].key;
  }
  renderSekmeler();
  renderPazarNotu();
}

function renderSekmeler() {
  const nav = document.getElementById("pazar-sekmeleri");
  nav.innerHTML = "";
  for (const pazar of pazarlar) {
    const btn = document.createElement("button");
    btn.className = "market-tab" + (pazar.key === aktifPazar ? " active" : "");
    btn.textContent = pazar.label;
    btn.addEventListener("click", () => pazarDegistir(pazar.key));
    nav.appendChild(btn);
  }
}

function renderPazarNotu() {
  const notEl = document.getElementById("pazar-notu");
  const not = aktifPazarBilgi().note;
  if (not) {
    notEl.textContent = "ℹ️ " + not;
    notEl.hidden = false;
  } else {
    notEl.hidden = true;
  }
}

function pazarDegistir(anahtar) {
  if (anahtar === aktifPazar) return;
  aktifPazar = anahtar;
  secilenSembol = null;
  renderSekmeler();
  renderPazarNotu();
  document.getElementById("detay-icerik").innerHTML =
    '<div class="detail-empty">Detayları görmek için soldaki tablodan bir sembol seçin.</div>';
  tarayiciYenile();
  portfoyYenile();
  simulasyonYenile();
  makroYenile();
  sinyalPerformansiYenile();
}

async function makroYenile() {
  if (!aktifPazar) return;
  const serit = document.getElementById("makro-serit");
  try {
    const gostergeler = await veriCek(`/api/${aktifPazar}/macro`);
    if (!gostergeler.length) {
      serit.hidden = true;
      return;
    }
    serit.innerHTML = gostergeler.map((g) => {
      const degisimSinif = (g.change_pct ?? 0) >= 0 ? "pnl-pos" : "pnl-neg";
      const degisimMetin = g.change_pct !== null ? `${g.change_pct >= 0 ? "+" : ""}${paraFormat(g.change_pct)}%` : "";
      return `
        <div class="macro-item" title="${g.description}">
          <span class="macro-label">${g.label}:</span>
          <span class="macro-price">${paraFormat(g.price)}</span>
          <span class="macro-change ${degisimSinif}">${degisimMetin}</span>
        </div>`;
    }).join("");
    serit.hidden = false;
  } catch (err) {
    serit.hidden = true;
  }
}

async function tarayiciYenile() {
  if (!aktifPazar) return;
  const minSkor = document.getElementById("min-skor").value;
  const sinyal = document.getElementById("sinyal-filtre").value;
  const params = new URLSearchParams({ min_score: minSkor });
  if (sinyal) params.set("signal", sinyal);

  try {
    const sonuclar = await veriCek(`/api/${aktifPazar}/scanner?${params.toString()}`);
    durumGuncelle(true);
    const govde = document.getElementById("tarayici-govde");
    govde.innerHTML = "";

    if (sonuclar.length === 0) {
      govde.innerHTML = '<tr><td colspan="5" class="empty-row">Kriterlere uyan sembol yok. Veriler birikiyor olabilir.</td></tr>';
      return;
    }

    for (const satir of sonuclar) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${satir.symbol}</strong></td>
        <td>${paraBirimli(satir.price)}</td>
        <td><span class="badge badge-${satir.signal}">${SINYAL_ETIKET[satir.signal] || satir.signal}</span></td>
        <td>
          <div class="score-bar-wrap">
            <span>${satir.score}</span>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${satir.score}%; background:${skorRengi(satir.score)}"></div></div>
          </div>
        </td>
        <td><span class="badge badge-${satir.risk_level}">${RISK_ETIKET[satir.risk_level] || satir.risk_level}</span></td>
      `;
      tr.addEventListener("click", () => sembolSec(satir.symbol));
      if (satir.symbol === secilenSembol) tr.style.background = "#16202c";
      govde.appendChild(tr);
    }
  } catch (err) {
    durumGuncelle(false);
    console.error(err);
  }
}

async function sembolSec(sembol) {
  secilenSembol = sembol;
  const icerik = document.getElementById("detay-icerik");
  icerik.innerHTML = '<div class="detail-empty">Yükleniyor...</div>';

  try {
    const detay = await veriCek(`/api/${aktifPazar}/signals/${sembol}`);
    renderDetay(detay);
  } catch (err) {
    icerik.innerHTML = `<div class="detail-empty">Bu sembol için henüz yeterli veri yok.</div>`;
  }
}

async function detaySessizYenile() {
  // Periyodik otomatik yenileme: seçili sembolü sessizce günceller, paneli
  // önce "Yükleniyor..." durumuna boşaltmaz. Aksi halde her 5 saniyede bir
  // ~1000px'lik detay paneli tek satıra küçülüp tekrar genişliyor, bu da
  // sayfanın sürekli aşağı/yukarı zıplaması gibi görünüyordu.
  const sembol = secilenSembol;
  if (!sembol) return;
  const uzunVadeEl = document.getElementById("uzun-vade-icerik");
  const haberEl = document.getElementById("haber-icerik");
  const korumaliIcerik = {
    uzunVade: uzunVadeEl ? uzunVadeEl.innerHTML : null,
    haber: haberEl ? haberEl.innerHTML : null,
  };

  try {
    const detay = await veriCek(`/api/${aktifPazar}/signals/${sembol}`);
    if (secilenSembol !== sembol) return; // kullanıcı bu sırada başka sembole geçmiş olabilir
    renderDetay(detay, korumaliIcerik);
  } catch (err) {
    // sessiz yenileme başarısız olursa mevcut içeriği olduğu gibi bırak
  }
}

const YETERLI_BAR_ESIGI = 250; // EMA200 için gereken tam pencere
const VERI_TAZELIK_ESIGI_SN = 30 * 60; // bu süreden uzun süredir yeni bar yoksa uyar

function saniyeFormat(saniye) {
  if (saniye < 3600) return `${Math.round(saniye / 60)} dakika`;
  if (saniye < 86400) return `${(saniye / 3600).toFixed(1)} saat`;
  return `${(saniye / 86400).toFixed(1)} gün`;
}

function renderDetay(detay, korumaliIcerik) {
  const icerik = document.getElementById("detay-icerik");
  const kategoriler = detay.category_scores;
  const birim = aktifPazarBilgi().currency_symbol;

  let veriUyarisiHtml = "";
  const barSayisi = detay.bars_available ?? 0;
  if (barSayisi < YETERLI_BAR_ESIGI) {
    const yuzde = Math.min(100, Math.round((barSayisi / YETERLI_BAR_ESIGI) * 100));
    veriUyarisiHtml = `
      <div class="market-note" style="margin:0 0 12px;border-radius:8px;">
        ℹ️ Veri birikimi devam ediyor: ${barSayisi}/${YETERLI_BAR_ESIGI} bar (%${yuzde}).
        Trend gibi bazı kategoriler (özellikle EMA200) tam olgunlaşana kadar düşük/eksik
        puanlanabilir — bu düşük skor "kötü hisse" anlamına gelmeyebilir, henüz yeterli
        geçmiş veri olmadığı anlamına gelir.
      </div>`;
  }

  let tazelikUyarisiHtml = "";
  const veriYasi = detay.data_age_seconds;
  if (veriYasi !== null && veriYasi !== undefined && veriYasi > VERI_TAZELIK_ESIGI_SN) {
    tazelikUyarisiHtml = `
      <div class="market-note" style="margin:0 0 12px;border-radius:8px;">
        ⏱️ Bu skor ${saniyeFormat(veriYasi)} önceki veriye dayanıyor, güncel olmayabilir.
        Bu genellikle piyasa kapalı olduğu için normaldir (gece, hafta sonu, tatil);
        piyasa açıkken uzun süre böyle kalırsa veri akışında bir aksama olabilir —
        gerçek zamanlı fiyatı aracı kurumunuzdan teyit edin.
      </div>`;
  }

  let kategoriHtml = "";
  for (const anahtar of ["trend", "momentum", "volume", "price_action", "risk_reward"]) {
    const deger = kategoriler[anahtar];
    const yuzde = (deger / 20) * 100;
    kategoriHtml += `
      <div class="category-row">
        <span>${KATEGORI_ETIKET[anahtar]}</span>
        <div class="cat-track"><div class="cat-fill" style="width:${yuzde}%"></div></div>
        <span>${deger}/20</span>
      </div>`;
  }

  let nedenlerHtml = detay.reasons.length
    ? `<ul class="reasons-list">${detay.reasons
        .map(
          (n) =>
            `<li class="${n.positive ? "reason-pos" : "reason-neg"}"><span class="reason-mark">${n.positive ? "▲" : "▼"}</span> ${n.text}</li>`
        )
        .join("")}</ul>`
    : '<p class="detail-empty">Belirgin bir gerekçe bulunamadı.</p>';

  let riskHtml = "";
  let stopFiyat = null;
  if (detay.risk_analysis) {
    const r = detay.risk_analysis;
    stopFiyat = r.stop_loss;
    riskHtml = `
      <div class="risk-grid">
        ${["entry_price", "stop_loss", "take_profit_1", "take_profit_2", "atr", "risk_reward_ratio"]
          .map(
            (alan) => `
          <div class="cell">
            <span class="label">${RISK_ALAN_ETIKET[alan]}</span>
            <span class="value">${paraFormat(r[alan])}</span>
          </div>`
          )
          .join("")}
      </div>`;
  }

  let buyZoneHtml = "";
  if (detay.buy_zone_low !== null && detay.buy_zone_low !== undefined) {
    buyZoneHtml = `
      <div class="buy-zone-box">
        <span class="label">Alım İçin Referans Bölge (geri çekilme senaryosu)</span>
        <span class="value">${paraBirimli(detay.buy_zone_low)} — ${paraBirimli(detay.buy_zone_high)}</span>
        <p class="hint">Bollinger orta bandı ile bir ATR altı arası. Fiyatın buraya geleceğinin garantisi değildir — mevcut volatiliteye göre hesaplanan bir referanstır.</p>
      </div>`;
  }

  let dipHtml = "";
  if (detay.dip_opportunity) {
    const dip = detay.dip_opportunity;
    const dipNedenler = dip.reasons
      .map(
        (n) =>
          `<li class="${n.positive ? "reason-pos" : "reason-neg"}"><span class="reason-mark">${n.positive ? "▲" : "▼"}</span> ${n.text}</li>`
      )
      .join("");
    dipHtml = `
      <div class="buy-zone-box" style="margin-top:10px;">
        <span class="label">🔻 Dip Fırsatı Tespit Edildi
          <span class="badge badge-${DIP_GUVEN_BADGE_SINIF[dip.confidence]}">${DIP_GUVEN_ETIKET[dip.confidence] || dip.confidence} güven</span>
        </span>
        <ul class="reasons-list" style="margin-top:6px;">${dipNedenler}</ul>
        <p class="hint">Trend-takip Fırsat Skoru'ndan tamamen ayrı, "aşırı satım + destek bandı + hacim" temelli bir tepki-alımı okuması.
          Bu, yukarıdaki Fırsat Skoru ile çelişebilir (bir hisse trend kurallarına göre Kaçının olurken aynı anda dip adayı olabilir) —
          kasıtlı olarak birleştirilmez, garanti değildir.</p>
      </div>`;
  }

  let gunlukTrendHtml = "";
  if (detay.daily_trend_up !== null && detay.daily_trend_up !== undefined) {
    const yukselis = detay.daily_trend_up === true;
    gunlukTrendHtml = `
      <p class="hint" style="margin:8px 0;">
        📅 Günlük Trend (EMA50/EMA200): <strong>${yukselis ? "Yükseliş ✅" : "Düşüş ⚠️"}</strong>
        — otomatik simülasyonda giriş onayı olarak kullanılır, Fırsat Skoru'nu etkilemez.
      </p>`;
  }

  icerik.innerHTML = `
    <div class="detail-symbol">
      <span class="sym">${detay.symbol}</span>
      <span class="price">${paraBirimli(detay.price)}</span>
    </div>
    <h3 style="font-size:13px;color:var(--accent);margin:0 0 6px;">⚡ Kısa Vadeli Teknik Sinyal</h3>
    ${tazelikUyarisiHtml}
    ${veriUyarisiHtml}
    <div class="detail-score">
      Toplam Fırsat Skoru: <strong>${detay.score}/100</strong> —
      <span class="badge badge-${detay.signal}">${SINYAL_ETIKET[detay.signal] || detay.signal}</span>
    </div>
    ${kategoriHtml}
    <h3 style="font-size:13px;color:var(--muted);margin:14px 0 6px;">Gerekçeler</h3>
    ${nedenlerHtml}
    <h3 style="font-size:13px;color:var(--muted);margin:14px 0 6px;">Risk Analizi (ATR bazlı, örnek senaryo — satış tabanları: Zarar Kes / Kâr Al)</h3>
    ${riskHtml || '<p class="detail-empty">Risk analizi için yeterli veri yok.</p>'}
    ${buyZoneHtml}
    ${dipHtml}
    ${gunlukTrendHtml}
    <h3 style="font-size:13px;color:var(--accent);margin:18px 0 6px;border-top:1px solid var(--panel-border);padding-top:14px;">📈 Uzun Vadeli Görünüm (Temel Analiz)</h3>
    <div id="uzun-vade-icerik">${(korumaliIcerik && korumaliIcerik.uzunVade) || '<p class="detail-empty">Yükleniyor...</p>'}</div>
    <h3 style="font-size:13px;color:var(--muted);margin:14px 0 6px;">📰 Son Haberler ve Duyarlılık</h3>
    <div id="haber-icerik">${(korumaliIcerik && korumaliIcerik.haber) || '<p class="detail-empty">Yükleniyor...</p>'}</div>
    <div class="calc-form">
      <h3>Pozisyon Büyüklüğü Hesaplayıcı</h3>
      <div class="calc-row">
        <input type="number" id="hesap-bakiye" placeholder="Hesap Bakiyesi (${birim})" value="100000" />
        <input type="number" id="risk-yuzde" placeholder="Risk Yüzdesi (%)" value="1" step="0.1" />
      </div>
      <div class="calc-row">
        <input type="number" id="giris-fiyat" placeholder="Giriş Fiyatı" value="${detay.price}" step="0.01" />
        <input type="number" id="stop-fiyat" placeholder="Stop Fiyatı" value="${stopFiyat ?? ""}" step="0.01" />
      </div>
      <button id="hesapla-btn">Hesapla</button>
      <div class="calc-result" id="hesap-sonuc"></div>
    </div>
    <p class="detail-empty" style="text-align:left;padding-top:14px;">${detay.disclaimer}</p>
  `;

  document.getElementById("hesapla-btn").addEventListener("click", pozisyonHesapla);
  haberleriYukle(detay.symbol);
  uzunVadeYukle(detay.symbol);
}

const SENTIMENT_ETIKET = {
  POSITIVE: "Olumlu",
  NEGATIVE: "Olumsuz",
  NEUTRAL: "Nötr",
  UNAVAILABLE: "Değerlendirilemedi",
};

const OUTLOOK_ETIKET = {
  FAVORABLE: "Olumlu",
  NEUTRAL: "Nötr",
  UNFAVORABLE: "Olumsuz",
  INSUFFICIENT_DATA: "Yetersiz Veri",
};
const OUTLOOK_BADGE_SINIF = {
  FAVORABLE: "STRONG_BUY_SETUP",
  NEUTRAL: "NEUTRAL",
  UNFAVORABLE: "AVOID",
  INSUFFICIENT_DATA: "NEUTRAL",
};
const TEMEL_ALAN_ETIKET = {
  trailing_pe: "F/K Oranı (Trailing)",
  forward_pe: "F/K Oranı (Forward)",
  price_to_book: "F/DD Oranı (Piyasa Değeri/Defter Değeri)",
  market_cap: "Piyasa Değeri",
  book_value_per_share: "Defter Değeri (Hisse Başına)",
  profit_margin_pct: "Net Kâr Marjı",
  ebitda_margin_pct: "FAVÖK Marjı",
  net_income: "Net Kâr (Yıllık)",
  revenue_growth_pct: "Gelir Büyümesi (Yıllık)",
  return_on_equity_pct: "Özkaynak Kârlılığı (ROE)",
  debt_to_equity: "Borç/Özkaynak Oranı",
  analyst_target_price: "Analist Ortalama Hedef Fiyat",
};
// Skorlanan alanlar (F/K, F/DD, kâr marjı, FAVÖK marjı, ROE, borç/özkaynak,
// büyüme) Uzun Vadeli Görünüm skoruna dahildir. Mutlak/ölçek bağımlı
// rakamlar (piyasa değeri, defter değeri, net kâr tutarı) şirket büyüklüğüne
// göre doğal olarak değiştiği için kasıtlı olarak SADECE bilgi amaçlı
// gösterilir, current_price/analyst_target_price ile aynı mantık.
const BUYUK_RAKAM_ALANLARI = new Set(["market_cap", "net_income"]);

function buyukSayiFormat(deger) {
  if (deger === null || deger === undefined || Number.isNaN(deger)) return "-";
  const birim = aktifPazarBilgi().currency_symbol;
  const isaret = deger < 0 ? "-" : "";
  const abs = Math.abs(deger);
  if (abs >= 1e12) return `${isaret}${(abs / 1e12).toFixed(2)} Trilyon ${birim}`;
  if (abs >= 1e9) return `${isaret}${(abs / 1e9).toFixed(2)} Milyar ${birim}`;
  if (abs >= 1e6) return `${isaret}${(abs / 1e6).toFixed(2)} Milyon ${birim}`;
  return paraBirimli(deger);
}

async function uzunVadeYukle(sembol) {
  const kutu = document.getElementById("uzun-vade-icerik");
  if (!kutu) return;
  try {
    const outlook = await veriCek(`/api/${aktifPazar}/fundamentals/${sembol}`);
    if (secilenSembol !== sembol) return;
    renderUzunVade(outlook);
  } catch (err) {
    kutu.innerHTML = '<p class="detail-empty">Temel analiz verisi yüklenemedi (özellik kapalı olabilir).</p>';
  }
}

function renderUzunVade(outlook) {
  const kutu = document.getElementById("uzun-vade-icerik");
  const f = outlook.fundamentals;

  if (outlook.label === "INSUFFICIENT_DATA" || !f) {
    if (outlook.likely_blocked) {
      kutu.innerHTML = `
        <p class="detail-empty" style="text-align:left;">
          ⚠️ Temel analiz verisi bu sunucudan şu anda alınamıyor — veri kaynağı (Yahoo Finance),
          bu barındırma ortamının IP adresini bu tür sorgular için kısıtlıyor. Bu, koddaki bir hata
          değil; masaüstü uygulamasında (kendi bilgisayarınızda) bu özellik sorunsuz çalışıyor.
        </p>`;
    } else {
      kutu.innerHTML = '<p class="detail-empty">Bu sembol için henüz yeterli temel veri toplanmadı (birkaç saat içinde güncellenir).</p>';
    }
    return;
  }

  const nedenlerHtml = outlook.reasons.length
    ? `<ul class="reasons-list">${outlook.reasons
        .map((n) => `<li class="${n.positive ? "reason-pos" : "reason-neg"}"><span class="reason-mark">${n.positive ? "▲" : "▼"}</span> ${n.text}</li>`)
        .join("")}</ul>`
    : '<p class="detail-empty">Belirgin bir gerekçe bulunamadı.</p>';

  const veriAlanlari = [
    "trailing_pe", "forward_pe", "price_to_book", "market_cap", "book_value_per_share",
    "profit_margin_pct", "ebitda_margin_pct", "net_income", "revenue_growth_pct",
    "return_on_equity_pct", "debt_to_equity", "analyst_target_price",
  ].filter((alan) => f[alan] !== null && f[alan] !== undefined);

  const veriGridHtml = veriAlanlari.length
    ? `<div class="risk-grid">${veriAlanlari.map((alan) => {
        let deger;
        if (BUYUK_RAKAM_ALANLARI.has(alan)) deger = buyukSayiFormat(f[alan]);
        else if (alan.endsWith("_pct")) deger = `%${paraFormat(f[alan])}`;
        else if (alan === "analyst_target_price" || alan === "book_value_per_share") deger = paraBirimli(f[alan]);
        else deger = paraFormat(f[alan]);
        return `<div class="cell"><span class="label">${TEMEL_ALAN_ETIKET[alan]}</span><span class="value">${deger}</span></div>`;
      }).join("")}</div>`
    : "";

  const analistHtml = f.analyst_recommendation
    ? `<p class="detail-empty" style="text-align:left;">Yahoo Finance analist konsensüsü: <strong>${f.analyst_recommendation}</strong></p>`
    : "";

  kutu.innerHTML = `
    <div class="detail-score" style="margin-bottom:10px;">
      Uzun Vadeli Görünüm Skoru: <strong>${outlook.score}/100</strong> —
      <span class="badge badge-${OUTLOOK_BADGE_SINIF[outlook.label]}">${OUTLOOK_ETIKET[outlook.label] || outlook.label}</span>
    </div>
    ${f.long_name ? `<p class="detail-empty" style="text-align:left;">${f.long_name}${f.sector ? " — " + f.sector : ""}</p>` : ""}
    ${veriGridHtml}
    ${analistHtml}
    <h3 style="font-size:12px;color:var(--muted);margin:12px 0 6px;">Gerekçeler</h3>
    ${nedenlerHtml}
    <p class="detail-empty" style="text-align:left;">${outlook.disclaimer}</p>
  `;
}

async function haberleriYukle(sembol) {
  const kutu = document.getElementById("haber-icerik");
  if (!kutu) return;
  try {
    const ozet = await veriCek(`/api/${aktifPazar}/news/${sembol}`);
    if (secilenSembol !== sembol) return; // kullanıcı bu sırada başka sembole geçmiş olabilir

    if (!ozet.items.length) {
      kutu.innerHTML = '<p class="detail-empty">Bu sembol için haber bulunamadı.</p>';
      return;
    }

    const yontemEtiket = ozet.sentiment_method === "finbert" ? "FinBERT (dil modeli)"
      : ozet.sentiment_method === "keyword" ? "basit anahtar kelime analizi"
      : "yöntem belirlenemedi";
    const ozetSatir = `
      <div class="news-summary">
        <span class="badge badge-${ozet.overall === "POSITIVE" ? "STRONG_BUY_SETUP" : ozet.overall === "NEGATIVE" ? "AVOID" : "NEUTRAL"}">
          Genel: ${SENTIMENT_ETIKET[ozet.overall] || ozet.overall}
        </span>
        <span class="news-counts">Olumlu ${ozet.positive_count} · Olumsuz ${ozet.negative_count} · Nötr ${ozet.neutral_count}</span>
      </div>
      <p class="detail-empty" style="text-align:left;font-size:11px;">Duyarlılık yöntemi: ${yontemEtiket}</p>`;

    const haberler = ozet.items
      .map((h) => {
        const tarih = h.published_at ? new Date(h.published_at).toLocaleDateString("tr-TR") : "";
        const sentimentSinif = h.sentiment === "POSITIVE" ? "reason-pos" : h.sentiment === "NEGATIVE" ? "reason-neg" : "";
        const baslik = h.link
          ? `<a href="${h.link}" target="_blank" rel="noopener">${h.title}</a>`
          : h.title;
        return `
          <li class="news-item">
            <span class="news-sentiment-dot ${sentimentSinif}"></span>
            <div>
              <div class="news-title">${baslik}</div>
              <div class="news-meta">${h.publisher || ""}${tarih ? " · " + tarih : ""} · ${SENTIMENT_ETIKET[h.sentiment] || h.sentiment}</div>
            </div>
          </li>`;
      })
      .join("");

    kutu.innerHTML = `${ozetSatir}<ul class="news-list">${haberler}</ul><p class="detail-empty" style="text-align:left;">${ozet.disclaimer}</p>`;
  } catch (err) {
    kutu.innerHTML = '<p class="detail-empty">Haberler yüklenemedi (özellik kapalı olabilir).</p>';
  }
}

async function pozisyonHesapla() {
  const sonucEl = document.getElementById("hesap-sonuc");
  const birim = aktifPazarBilgi().currency_symbol;
  const payload = {
    account_balance: parseFloat(document.getElementById("hesap-bakiye").value),
    risk_percent: parseFloat(document.getElementById("risk-yuzde").value),
    entry_price: parseFloat(document.getElementById("giris-fiyat").value),
    stop_price: parseFloat(document.getElementById("stop-fiyat").value),
  };

  try {
    const sonuc = await veriCek("/api/risk/position-size", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    sonucEl.innerHTML = `
      Önerilen adet: <strong>${paraFormat(sonuc.shares)}</strong> ·
      Riske edilen tutar: <strong>${paraFormat(sonuc.risk_amount)} ${birim}</strong> ·
      Pozisyon değeri: <strong>${paraFormat(sonuc.position_value)} ${birim}</strong>`;
  } catch (err) {
    sonucEl.textContent = "Hesaplanamadı: " + err.message;
  }
}

async function portfoyYenile() {
  if (!aktifPazar) return;
  try {
    const pf = await veriCek(`/api/${aktifPazar}/portfolio`);
    document.getElementById("pf-nakit").textContent = paraBirimli(pf.cash);
    document.getElementById("pf-deger").textContent = paraBirimli(pf.equity);

    const gerceklesenEl = document.getElementById("pf-gerceklesen");
    gerceklesenEl.textContent = paraBirimli(pf.realized_pnl);
    gerceklesenEl.className = "stat-value " + (pf.realized_pnl >= 0 ? "pnl-pos" : "pnl-neg");

    const gerceklesmeyenEl = document.getElementById("pf-gerceklesmeyen");
    gerceklesmeyenEl.textContent = paraBirimli(pf.unrealized_pnl);
    gerceklesmeyenEl.className = "stat-value " + (pf.unrealized_pnl >= 0 ? "pnl-pos" : "pnl-neg");

    const govde = document.getElementById("pozisyon-govde");
    govde.innerHTML = "";
    if (pf.positions.length === 0) {
      govde.innerHTML = '<tr><td colspan="5" class="empty-row">Açık pozisyon yok.</td></tr>';
      return;
    }
    for (const pos of pf.positions) {
      const pnl = (pos.current_price - pos.average_price) * pos.quantity;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${pos.symbol}</strong></td>
        <td>${paraFormat(pos.quantity)}</td>
        <td>${paraBirimli(pos.average_price)}</td>
        <td>${paraBirimli(pos.current_price)}</td>
        <td class="${pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${paraBirimli(pnl)}</td>
      `;
      govde.appendChild(tr);
    }
  } catch (err) {
    console.error(err);
  }
}

document.getElementById("min-skor").addEventListener("input", (e) => {
  document.getElementById("min-skor-deger").textContent = e.target.value;
});
document.getElementById("min-skor").addEventListener("change", tarayiciYenile);
document.getElementById("sinyal-filtre").addEventListener("change", tarayiciYenile);

function gunFormat(gun) {
  if (gun === null || gun === undefined) return "-";
  const saat = gun * 24;
  if (saat < 1) return `${Math.round(saat * 60)} dakika`;
  if (gun < 1) return `${saat.toFixed(1)} saat`;
  return `${gun.toFixed(1)} gün`;
}

async function simulasyonYenile() {
  if (!aktifPazar) return;
  const kutu = document.getElementById("simulasyon-icerik");
  try {
    const sim = await veriCek(`/api/${aktifPazar}/simulation/status`);
    renderSimulasyon(sim);
  } catch (err) {
    kutu.innerHTML = '<p class="detail-empty">Simülasyon özelliği bu piyasada kapalı.</p>';
  }
}

function renderSimulasyon(sim) {
  const kutu = document.getElementById("simulasyon-icerik");
  const birim = sim.currency_symbol;

  if (sim.status === "NOT_STARTED") {
    kutu.innerHTML = `
      <p class="detail-empty" style="text-align:left;">
        Sistem, kendi kurallı sinyallerine göre (BUY_SETUP/STRONG_BUY_SETUP'ta alım, zarar-kes/kâr-al/KAÇININ'da satım)
        belirlediğiniz süre boyunca otomatik olarak sanal alım-satım yapar ve sonunda bir kâr/zarar raporu sunar.
      </p>
      <div class="sim-start-form">
        <label>Başlangıç Bakiyesi (${birim})
          <input type="number" id="sim-bakiye" value="10000" min="100" step="100" />
        </label>
        <label>Süre (gün)
          <input type="number" id="sim-gun" value="7" min="1" max="30" step="1" />
        </label>
        <button id="sim-baslat-btn">Simülasyonu Başlat</button>
      </div>
      <p class="detail-empty" style="text-align:left;">${sim.disclaimer}</p>`;
    document.getElementById("sim-baslat-btn").addEventListener("click", simulasyonBaslat);
    return;
  }

  const durumRozeti = sim.status === "RUNNING"
    ? '<span class="badge badge-STRONG_BUY_SETUP">Çalışıyor</span>'
    : '<span class="badge sim-badge-completed">Tamamlandı</span>';

  const getiriSinif = (sim.total_return_pct ?? 0) >= 0 ? "pnl-pos" : "pnl-neg";
  const ilerlemeYuzde = sim.status === "COMPLETED" ? 100
    : Math.min(100, Math.max(0, 100 - (sim.days_remaining / ((sim.ends_at && sim.started_at)
        ? (new Date(sim.ends_at) - new Date(sim.started_at)) / 86400000 : 7)) * 100));

  const pozisyonSatirlari = sim.positions.length
    ? sim.positions.map((p) => `
        <tr>
          <td><strong>${p.symbol}</strong></td>
          <td>${paraFormat(p.quantity)}</td>
          <td>${birim} ${paraFormat(p.average_price)}</td>
          <td>${p.current_price !== null ? birim + " " + paraFormat(p.current_price) : "-"}</td>
          <td class="${(p.unrealized_pnl ?? 0) >= 0 ? "pnl-pos" : "pnl-neg"}">${p.unrealized_pnl !== null ? birim + " " + paraFormat(p.unrealized_pnl) : "-"}</td>
          <td>${p.stop_loss !== null && p.stop_loss !== undefined ? birim + " " + paraFormat(p.stop_loss) : "-"}</td>
        </tr>`).join("")
    : '<tr><td colspan="6" class="empty-row">Açık pozisyon yok.</td></tr>';

  const islemSatirlari = sim.recent_trades.length
    ? sim.recent_trades.map((t) => `
        <tr>
          <td>${new Date(t.timestamp).toLocaleString("tr-TR")}</td>
          <td><strong>${t.symbol}</strong></td>
          <td><span class="badge badge-${t.action === "BUY" ? "STRONG_BUY_SETUP" : "AVOID"}">${t.action === "BUY" ? "ALIM" : "SATIM"}</span></td>
          <td>${birim} ${paraFormat(t.price)}</td>
          <td>${paraFormat(t.quantity)}</td>
          <td>${t.realized_pnl !== null ? `<span class="${t.realized_pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${birim} ${paraFormat(t.realized_pnl)}</span>` : "-"}</td>
          <td>${t.reason}</td>
        </tr>`).join("")
    : '<tr><td colspan="7" class="empty-row">Henüz işlem yok.</td></tr>';

  kutu.innerHTML = `
    <div class="detail-score" style="margin-bottom:10px;">
      ${durumRozeti}
      ${sim.status === "RUNNING" ? `— Kalan süre: <strong>${gunFormat(sim.days_remaining)}</strong>` : `— Tamamlandı: ${sim.completed_at ? new Date(sim.completed_at).toLocaleString("tr-TR") : ""}`}
    </div>
    ${sim.status === "RUNNING" ? `
      <div class="sim-progress"><div class="sim-progress-track"><div class="sim-progress-fill" style="width:${ilerlemeYuzde}%"></div></div></div>
      <button id="sim-durdur-btn" class="sim-stop-btn">Simülasyonu Durdur</button>` : ""}
    ${sim.peak_equity !== null && sim.peak_equity !== undefined ? `
      <p class="hint" style="margin:6px 0 10px;">
        📉 Zirve Özkaynak: ${birim} ${paraFormat(sim.peak_equity)} — Şu anki düşüş: %${paraFormat(sim.drawdown_pct)}
        ${sim.trading_paused ? ` — <strong style="color:var(--red);">⏸️ Yeni pozisyon açma geçici durduruldu (zarar tavanı aşıldı)</strong>` : ""}
      </p>` : ""}
    <div class="portfolio-summary">
      <div class="stat"><span class="stat-label">Başlangıç</span><span class="stat-value">${birim} ${paraFormat(sim.initial_cash)}</span></div>
      <div class="stat"><span class="stat-label">Güncel Toplam Değer</span><span class="stat-value">${birim} ${paraFormat(sim.equity)}</span></div>
      <div class="stat"><span class="stat-label">Toplam Getiri</span><span class="stat-value ${getiriSinif}">%${paraFormat(sim.total_return_pct)}</span></div>
      <div class="stat"><span class="stat-label">Gerçekleşen K/Z</span><span class="stat-value ${(sim.realized_pnl ?? 0) >= 0 ? "pnl-pos" : "pnl-neg"}">${birim} ${paraFormat(sim.realized_pnl)}</span></div>
      <div class="stat"><span class="stat-label">İşlem Sayısı</span><span class="stat-value">${sim.trade_count}</span></div>
    </div>
    <table class="portfolio-table">
      <thead><tr><th>Sembol</th><th>Adet</th><th>Ort. Maliyet</th><th>Güncel Fiyat</th><th>K/Z</th><th>Zarar-Kes (İz Süren)</th></tr></thead>
      <tbody>${pozisyonSatirlari}</tbody>
    </table>
    <div class="sim-trades-table">
      <h3>İşlem Geçmişi</h3>
      <table class="portfolio-table">
        <thead><tr><th>Zaman</th><th>Sembol</th><th>Yön</th><th>Fiyat</th><th>Adet</th><th>K/Z</th><th>Gerekçe</th></tr></thead>
        <tbody>${islemSatirlari}</tbody>
      </table>
    </div>
    ${sim.status === "COMPLETED" ? `
      <div class="sim-start-form" style="margin-top:14px;">
        <label>Yeni Başlangıç Bakiyesi (${birim})<input type="number" id="sim-bakiye" value="10000" min="100" step="100" /></label>
        <label>Süre (gün)<input type="number" id="sim-gun" value="7" min="1" max="30" step="1" /></label>
        <button id="sim-baslat-btn">Yeni Simülasyon Başlat</button>
      </div>` : ""}
    <p class="detail-empty" style="text-align:left;margin-top:10px;">${sim.disclaimer}</p>
  `;

  const baslatBtn = document.getElementById("sim-baslat-btn");
  if (baslatBtn) baslatBtn.addEventListener("click", simulasyonBaslat);
  const durdurBtn = document.getElementById("sim-durdur-btn");
  if (durdurBtn) durdurBtn.addEventListener("click", simulasyonDurdur);
}

async function simulasyonBaslat() {
  const btn = document.getElementById("sim-baslat-btn");
  const bakiye = parseFloat(document.getElementById("sim-bakiye").value);
  const gun = parseFloat(document.getElementById("sim-gun").value);
  btn.disabled = true;
  btn.textContent = "Başlatılıyor...";
  try {
    await veriCek(`/api/${aktifPazar}/simulation/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_cash: bakiye, duration_days: gun }),
    });
    await simulasyonYenile();
  } catch (err) {
    alert("Simülasyon başlatılamadı: " + err.message);
    btn.disabled = false;
    btn.textContent = "Simülasyonu Başlat";
  }
}

async function simulasyonDurdur() {
  const onay = confirm(
    "Simülasyonu durdurmak istediğinizden emin misiniz?\n\n" +
    "Açık pozisyonlar varsa güncel fiyattan satılacak ve simülasyon sona erecek. Bu işlem geri alınamaz."
  );
  if (!onay) return;

  const btn = document.getElementById("sim-durdur-btn");
  btn.disabled = true;
  btn.textContent = "Durduruluyor...";
  try {
    await veriCek(`/api/${aktifPazar}/simulation/stop`, { method: "POST" });
    await simulasyonYenile();
  } catch (err) {
    alert("Simülasyon durdurulamadı: " + err.message);
    btn.disabled = false;
    btn.textContent = "Simülasyonu Durdur";
  }
}

const SINYAL_SIRALAMA = ["STRONG_BUY_SETUP", "BUY_SETUP", "WATCH", "NEUTRAL", "AVOID"];
const HORIZON_SIRALAMA = [5, 10, 20];

async function sinyalPerformansiYenile() {
  if (!aktifPazar) return;
  const kutu = document.getElementById("sinyal-performans-icerik");
  try {
    const veri = await veriCek(`/api/${aktifPazar}/signal-performance`);
    renderSinyalPerformansi(veri);
  } catch (err) {
    kutu.innerHTML = '<p class="detail-empty">Sinyal performansı yüklenemedi.</p>';
  }
}

function renderSinyalPerformansi(veri) {
  const kutu = document.getElementById("sinyal-performans-icerik");

  if (!veri.length) {
    kutu.innerHTML = `
      <p class="detail-empty" style="text-align:left;">
        Sistem, her sinyal değişiminde bunu kaydedip 5/10/20 gün sonra fiyatla karşılaştırıyor —
        "STRONG_BUY_SETUP dediklerimiz gerçekten yükseliyor mu?" sorusuna kendi geçmişinden cevap
        vermesi için. En az 3 örneği biriken sinyal/süre kombinasyonları burada görünecek —
        henüz yeterli geçmiş yok.
      </p>`;
    return;
  }

  const harita = {};
  for (const satir of veri) {
    harita[satir.signal] = harita[satir.signal] || {};
    harita[satir.signal][satir.horizon_days] = satir;
  }

  const satirlarHtml = SINYAL_SIRALAMA.filter((s) => harita[s])
    .map((sinyal) => {
      const hucreler = HORIZON_SIRALAMA.map((h) => {
        const hucre = harita[sinyal][h];
        if (!hucre) return `<td class="detail-empty">—</td>`;
        const sinif = hucre.avg_return_pct >= 0 ? "pnl-pos" : "pnl-neg";
        return `<td class="${sinif}">%${paraFormat(hucre.avg_return_pct)} <span style="color:var(--muted);font-size:11px;">(n=${hucre.sample_count})</span></td>`;
      }).join("");
      return `
        <tr>
          <td><span class="badge badge-${sinyal}">${SINYAL_ETIKET[sinyal] || sinyal}</span></td>
          ${hucreler}
        </tr>`;
    })
    .join("");

  kutu.innerHTML = `
    <p class="detail-empty" style="text-align:left;">
      Her sinyal ilk oluştuğunda kaydedilir; belirtilen gün sayısı sonra fiyatla karşılaştırılıp
      ortalama getiri hesaplanır. En az 3 örneği olmayan kombinasyonlar gösterilmez.
    </p>
    <table class="portfolio-table">
      <thead><tr><th>Sinyal</th><th>5 Gün Sonra</th><th>10 Gün Sonra</th><th>20 Gün Sonra</th></tr></thead>
      <tbody>${satirlarHtml}</tbody>
    </table>
    <p class="detail-empty" style="text-align:left;margin-top:10px;">
      Geçmiş performans gelecekteki sonuçları garanti etmez. Bu bir yatırım tavsiyesi değildir.
    </p>`;
}

async function baslat() {
  await pazarlariYukle();
  tarayiciYenile();
  portfoyYenile();
  simulasyonYenile();
  makroYenile();
  sinyalPerformansiYenile();
}

baslat();
setInterval(tarayiciYenile, 5000);
setInterval(portfoyYenile, 5000);
setInterval(simulasyonYenile, 5000);
setInterval(makroYenile, 60000);
setInterval(sinyalPerformansiYenile, 300000); // gün-bazlı veri, sık yenilemeye gerek yok
setInterval(() => {
  if (secilenSembol) detaySessizYenile();
}, 5000);
