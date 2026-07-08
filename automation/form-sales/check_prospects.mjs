#!/usr/bin/env node
/**
 * フォーム営業 見込み客診断＋文面生成ツール
 *
 * 使い方:
 *   node check_prospects.mjs prospects.csv
 *
 * 入力: CSV「社名,URL,業種」(1行目ヘッダ)。URLなし(サイト未保有)は URL欄を空に。
 * 出力: output/diagnosis_<日付>.csv  … 優先度スコア順の診断結果
 *       output/messages_<日付>.md   … 1社ごとのパーソナライズ済み送信文(コピペ用)
 *
 * 診断項目: SSL / スマホ対応(viewport) / コピーライト年 / 営業お断り表記
 * sent.csv に記録済みの相手・do-not-contact.csv の相手は自動で除外する。
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const TIMEOUT_MS = 15000;
const UA = 'Mozilla/5.0 (compatible; ITS-SiteCheck/1.0)';
const THIS_YEAR = new Date().getFullYear();

// ---------- CSV ----------
function parseCsv(text) {
  return text.replace(/^﻿/, '').split(/\r?\n/).filter(l => l.trim())
    .map(line => line.split(',').map(c => c.trim()));
}
function loadSet(file, col = 0) {
  const p = join(HERE, file);
  if (!existsSync(p)) return new Set();
  return new Set(parseCsv(readFileSync(p, 'utf8')).slice(1).map(r => normalizeKey(r[col] || '')));
}
const normalizeKey = s => s.toLowerCase().replace(/^https?:\/\//, '').replace(/\/$/, '');

// ---------- 診断 ----------
async function fetchSite(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers: { 'User-Agent': UA }, redirect: 'follow' });
    const html = (await res.text()).slice(0, 500000);
    return { ok: res.ok, finalUrl: res.url, html, error: res.ok ? undefined : `HTTP ${res.status}` };
  } catch (e) {
    return { ok: false, error: e.name === 'AbortError' ? 'timeout' : e.message };
  } finally { clearTimeout(timer); }
}

function diagnose(html, finalUrl) {
  const d = { issues: [], score: 0 };
  d.https = finalUrl.startsWith('https://');
  if (!d.https) { d.issues.push('SSLなし(「保護されていない通信」警告)'); d.score += 3; }

  d.mobile = /<meta[^>]+name=["']viewport["']/i.test(html);
  if (!d.mobile) { d.issues.push('スマホ非対応の可能性(viewportなし)'); d.score += 3; }

  const years = [...html.matchAll(/(?:©|&copy;|copyright|Copyright)[^<]{0,60}?((?:19|20)\d{2})/g)]
    .map(m => parseInt(m[1], 10)).filter(y => y >= 1995 && y <= THIS_YEAR);
  d.copyrightYear = years.length ? Math.max(...years) : null;
  if (d.copyrightYear && THIS_YEAR - d.copyrightYear >= 3) {
    d.issues.push(`更新が止まっている可能性(表記が${d.copyrightYear}年)`); d.score += 2;
  }

  d.salesRefused = /営業[^。]{0,12}(お断り|御断り|ご遠慮|固くお断り)|セールス[^。]{0,12}お断り/.test(html);
  const t = html.match(/<title[^>]*>([^<]{1,120})<\/title>/i);
  d.title = t ? t[1].trim() : '';
  return d;
}

// ---------- 文面生成 ----------
const ISSUE_LINE = {
  ssl: 'アドレスが「http」のままのため、Google Chrome等で「保護されていない通信」という警告が表示される状態になっており、お問い合わせの機会損失につながる可能性がございます',
  mobile: 'スマートフォンで拝見した際にパソコン向けの表示のままとなっており、現在7割以上を占めるスマホからの閲覧者様が見づらい状態かと存じます',
  old: '最終更新からお時間が経っているようにお見受けし、現在の事業内容と表示内容にズレが生じていないかと拝察いたしました',
  none: 'Web検索した際に公式ホームページが見当たらず、お客様が正確な情報にたどり着けていない可能性があると感じました',
};

function buildMessage(name, d) {
  let reason, offer;
  if (!d) { reason = ISSUE_LINE.none; offer = '1ページ構成のホームページを3万円台・最短3営業日で新規制作'; }
  else if (!d.https) { reason = ISSUE_LINE.ssl; offer = '警告の解消を含むリニューアルを10万円〜'; }
  else if (!d.mobile) { reason = ISSUE_LINE.mobile; offer = 'スマホ対応リニューアルを10万円〜(1ページ構成なら3万円台〜)'; }
  else if (d.copyrightYear && THIS_YEAR - d.copyrightYear >= 3) { reason = ISSUE_LINE.old; offer = 'リニューアルと月5,000円〜の更新代行'; }
  else { reason = 'より成果につながる改善余地があるのではと拝見しました'; offer = '無料診断とお見積り'; }

  return `${name} ご担当者様

突然のご連絡失礼いたします。ホームページ制作・システム開発を行っております、ITS合同会社の高橋と申します。

貴社のホームページを拝見したところ、${reason}。

弊社はAIを活用した開発体制により、${offer}にてご提供しております。
・お見積り、ご相談は無料です
・制作会社の相場の半額以下、最短3営業日での納品が可能です

ご興味をお持ちいただけましたら、本メールへのご返信、または下記までお気軽にご連絡ください。
現状の簡易診断結果だけでもお送りいたします。

不要の場合はご放念ください。お忙しいところ失礼いたしました。

ITS合同会社 代表 高橋賢弥
Mail: k.takahashi.7755@gmail.com
Web: (サイトURL)`;
}

// ---------- main ----------
const inFile = process.argv[2];
if (!inFile) { console.error('使い方: node check_prospects.mjs prospects.csv'); process.exit(1); }

const rows = parseCsv(readFileSync(resolve(inFile), 'utf8')).slice(1);
const sent = loadSet('sent.csv');
const dnc = loadSet('do-not-contact.csv');

const results = [];
for (const [name, url, industry] of rows) {
  if (!name) continue;
  const key = normalizeKey(url || name);
  if (sent.has(key) || sent.has(normalizeKey(name))) { console.log(`skip(送信済): ${name}`); continue; }
  if (dnc.has(key) || dnc.has(normalizeKey(name))) { console.log(`skip(連絡禁止): ${name}`); continue; }

  if (!url) {
    results.push({ name, url: '', industry, score: 4, issues: 'サイトなし', refused: false, msg: buildMessage(name, null) });
    console.log(`✓ ${name} — サイトなし(score 4)`);
    continue;
  }
  process.stdout.write(`checking ${name} (${url}) ... `);
  const site = await fetchSite(url.startsWith('http') ? url : 'https://' + url);
  if (!site.ok) {
    // https失敗 → httpで再試行(SSLなしサイトの検出)
    const retry = await fetchSite('http://' + url.replace(/^https?:\/\//, ''));
    if (!retry.ok) { console.log(`取得失敗(${site.error}) → 手動確認へ`); results.push({ name, url, industry, score: 1, issues: `取得失敗:${site.error}`, refused: false, msg: buildMessage(name, null) }); continue; }
    Object.assign(site, retry);
  }
  const d = diagnose(site.html, site.finalUrl);
  if (d.salesRefused) { console.log('営業お断り表記 → 除外'); results.push({ name, url, industry, score: -1, issues: '営業お断り表記あり(送信禁止)', refused: true, msg: '' }); continue; }
  results.push({ name, url, industry, score: d.score, issues: d.issues.join(' / ') || '大きな問題なし', refused: false, msg: buildMessage(name, d) });
  console.log(`score ${d.score} [${d.issues.join(', ') || 'OK'}]`);
}

results.sort((a, b) => b.score - a.score);
const stamp = new Date().toISOString().slice(0, 10);
const outDir = join(HERE, 'output');
mkdirSync(outDir, { recursive: true });

writeFileSync(join(outDir, `diagnosis_${stamp}.csv`),
  '﻿社名,URL,業種,優先度,検出した課題\n' +
  results.map(r => [r.name, r.url, r.industry || '', r.score, r.issues].join(',')).join('\n'), 'utf8');

writeFileSync(join(outDir, `messages_${stamp}.md`),
  `# フォーム送信文面（${stamp}生成・優先度順）\n\n` +
  `> 送信前チェック: ①フォームページに「営業お断り」がないか一瞥 ②社名の誤りがないか ③送信したら sent.csv に「社名,URL,${stamp}」を追記\n\n` +
  results.filter(r => !r.refused && r.msg).map((r, i) =>
    `---\n\n## ${i + 1}. ${r.name}（優先度${r.score}）\n- URL: ${r.url || 'サイトなし'}\n- 課題: ${r.issues}\n\n\`\`\`\n${r.msg}\n\`\`\`\n`).join('\n'), 'utf8');

const excluded = results.filter(r => r.refused).length;
console.log(`\n完了: ${results.length}件診断 / 営業お断り除外 ${excluded}件`);
console.log(`→ ${outDir}/diagnosis_${stamp}.csv`);
console.log(`→ ${outDir}/messages_${stamp}.md`);
