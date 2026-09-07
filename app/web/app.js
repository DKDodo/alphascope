const SINYAL_ETIKET = {
  STRONG_BUY_SETUP: "Güçlü Alım Fırsatı",
  BUY_SETUP: "Alım Fırsatı",
  WATCH: "İzlemede",
  NEUTRAL: "Nötr",
  AVOID: "Kaçının",
};

const RISK_ETIKET = { LOW: "Düşük", MEDIUM: "Orta", HIGH: "Yüksek" };

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

function renderDetay(detay) {
  const icerik = document.getElementById("detay-icerik");
  const kategoriler = detay.category_scores;
  const birim = aktifPazarBilgi().currency_symbol;

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

  icerik.innerHTML = `
    <div class="detail-symbol">
      <span class="sym">${detay.symbol}</span>
      <span class="price">${paraBirimli(detay.price)}</span>
    </div>
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
    <h3 style="font-size:13px;color:var(--muted);margin:14px 0 6px;">📰 Son Haberler ve Duyarlılık</h3>
    <div id="haber-icerik"><p class="detail-empty">Yükleniyor...</p></div>
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
}

const SENTIMENT_ETIKET = {
  POSITIVE: "Olumlu",
  NEGATIVE: "Olumsuz",
  NEUTRAL: "Nötr",
  UNAVAILABLE: "Değerlendirilemedi",
};

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

    const ozetSatir = `
      <div class="news-summary">
        <span class="badge badge-${ozet.overall === "POSITIVE" ? "STRONG_BUY_SETUP" : ozet.overall === "NEGATIVE" ? "AVOID" : "NEUTRAL"}">
          Genel: ${SENTIMENT_ETIKET[ozet.overall] || ozet.overall}
        </span>
        <span class="news-counts">Olumlu ${ozet.positive_count} · Olumsuz ${ozet.negative_count} · Nötr ${ozet.neutral_count}</span>
      </div>`;

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

async function baslat() {
  await pazarlariYukle();
  tarayiciYenile();
  portfoyYenile();
}

baslat();
setInterval(tarayiciYenile, 5000);
setInterval(portfoyYenile, 5000);
setInterval(() => {
  if (secilenSembol) sembolSec(secilenSembol);
}, 5000);
