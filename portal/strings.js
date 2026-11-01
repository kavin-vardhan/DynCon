// Every word the portal can put on screen, in one table.
//
// JP is machine-drafted — needs native review.  (A native speaker should read this file
// end to end before the booth; nothing else in the portal contains text, so this one file
// is the whole review.)
//
// Rules this table keeps, from CLAUDE.md rule 3 and specs/portal_spec_v1.md §1:
//   * every entry has BOTH languages. The JP line is shown on top, the EN under it.
//   * no game titles, no studio or brand names, no real money words. "Game A" / "Game B",
//     slots A1-B2, "another brand" for the rivals, and credits are always labelled
//     "demo credits - not real money".
//   * "Dynamic Contents" is the platform's own wordmark, not a brand in the tour, so it is
//     the one proper noun allowed here.

export const STRINGS = {
  // ---------------------------------------------------------------- chrome
  app_name:            { jp: 'ダイナミックコンテンツ',        en: 'Dynamic Contents' },
  your_brand:          { jp: 'あなたのブランド',              en: 'Your brand' },
  wallet_available:    { jp: '使えるクレジット',              en: 'Available' },
  wallet_held:         { jp: '確保中',                        en: 'Held' },
  wallet_charged:      { jp: '支払い済み',                    en: 'Charged' },
  demo_credits_note:   { jp: 'デモ用クレジット — 実際のお金ではありません',
                         en: 'demo credits — not real money' },
  clock_label:         { jp: 'デモ時間',                      en: 'demo time' },
  pad_offline:         { jp: 'コントローラー未接続',          en: 'No pad — keyboard works' },

  // ---------------------------------------------------------------- button hints
  hint_move:           { jp: '移動',                          en: 'Move' },
  hint_select:         { jp: '決定',                          en: 'Select' },
  hint_back:           { jp: '戻る',                          en: 'Back' },
  hint_start:          { jp: 'はじめる',                      en: 'Start' },
  hint_upload:         { jp: 'アップロード',                  en: 'Upload' },
  hint_next:           { jp: '次へ',                          en: 'Continue' },
  hint_pick_slot:      { jp: 'スロットを選ぶ',                en: 'Hop between slots' },
  hint_bid:            { jp: '入札へ',                        en: 'Go to bidding' },

  // ---------------------------------------------------------------- 0 attract
  attract_tagline:     { jp: 'ゲームの中の空きスペースを、ゲームを更新せずに入れ替える',
                         en: 'Content in the slots of a live game — no patch, no restart' },
  attract_now_showing: { jp: 'いまスロットに出ているもの',    en: 'On the slots right now' },
  attract_auctions:    { jp: '進行中のオークション',          en: 'Auctions running now' },
  attract_start:       { jp: 'A ボタンではじめる',            en: 'Press A to start' },
  attract_role:        { jp: 'ブランドとして参加します',      en: 'You take the brand’s seat' },
  showing_rival:       { jp: '別のブランド',                  en: 'Another brand' },
  showing_default:     { jp: 'ゲーム側の標準',                en: 'The game’s own' },
  showing_you:         { jp: 'あなたのコンテンツ',            en: 'Your content' },
  showing_none:        { jp: '空き',                          en: 'Empty' },
  holder_rival:        { jp: '別ブランドが最高',              en: 'Another brand leads' },
  holder_you:          { jp: 'あなたが最高額',                en: 'You lead' },

  // ---------------------------------------------------------------- 1 brand
  brand_title:         { jp: 'ブランドをつくる',              en: 'Create your brand' },
  brand_sub:           { jp: '色とマークを選んでください。あなたのコンテンツの看板に出ます。',
                         en: 'Pick a colour and an emblem. They go on your content’s sign.' },
  brand_colours:       { jp: '色',                            en: 'Colour' },
  brand_emblems:       { jp: 'マーク',                        en: 'Emblem' },
  brand_preview:       { jp: '看板プレビュー',                en: 'Sign preview' },
  brand_confirm:       { jp: 'このブランドではじめる',        en: 'Use this brand' },
  brand_wallet:        { jp: '2,000 デモクレジットを受け取りました',
                         en: 'You have 2,000 demo credits' },
  brand_no_names:      { jp: '名前は使いません。色とマークだけがあなたの目印です。',
                         en: 'No names anywhere — a colour and an emblem are your whole identity.' },

  // ---------------------------------------------------------------- 2 upload
  upload_title:        { jp: 'コンテンツをアップロード',      en: 'Upload your content' },
  upload_your_computer:{ jp: 'あなたのコンピューター',        en: 'Your computer' },
  upload_pick:         { jp: 'ファイルを選んで A を押してください',
                         en: 'Choose a file and press A' },
  upload_reading:      { jp: 'ファイルを読み込んでいます',    en: 'Reading from your computer' },
  upload_sending:      { jp: 'アップロードしています',        en: 'Uploading' },
  upload_checking:     { jp: 'プラットフォームが確認しています',
                         en: 'The platform is checking it' },
  upload_checks:       { jp: '4 つのチェック',                en: 'The four checks' },
  check_package:       { jp: 'パッケージ',                    en: 'Package' },
  check_rating:        { jp: 'レーティング',                  en: 'Rating' },
  check_fit:           { jp: 'サイズ',                        en: 'Fit' },
  check_sign:          { jp: '署名',                          en: 'Sign' },
  check_waiting:       { jp: '待機中',                        en: 'Waiting' },
  check_skipped:       { jp: '実行されませんでした',          en: 'Did not run' },
  upload_approved:     { jp: '承認されました',                en: 'Approved' },
  upload_rejected:     { jp: '受け付けられませんでした',      en: 'Rejected' },
  upload_my_content:   { jp: 'マイコンテンツ',                en: 'My content' },
  upload_again:        { jp: '別のファイルを試す',            en: 'Try another file' },
  upload_continue:     { jp: 'ゲームを選ぶ',                  en: 'Pick a game' },
  upload_size_class:   { jp: 'サイズクラス',                  en: 'Size class' },
  upload_bounds:       { jp: '大きさ',                        en: 'Measured size' },
  upload_fits_in:      { jp: '入るスロット',                  en: 'Fits these slots' },
  upload_file_note:    { jp: 'このファイルは落ちるようにつくってあります',
                         en: 'This file is built to fail' },
  upload_empty:        { jp: 'まだありません',                en: 'Nothing yet' },

  // ---------------------------------------------------------------- 3 games
  games_title:         { jp: 'ゲームを選ぶ',                  en: 'Pick a game' },
  games_sub:           { jp: '同じコンテンツが、どちらのゲームでも使えます',
                         en: 'One piece of content, any game on the platform' },
  games_slots:         { jp: 'ダイナミックスロット',          en: 'Dynamic slots' },
  games_players:       { jp: 'オンラインのプレイヤー',        en: 'Players online' },
  games_badge_booth:   { jp: 'このブースでプレイ中',          en: 'Playing at this booth' },
  games_registered:    { jp: '開発元がスロットマップを登録済み',
                         en: 'Slot map registered by the developer' },

  // ---------------------------------------------------------------- 4 slot map
  map_title:           { jp: 'スロットマップ',                en: 'Slot map' },
  map_sub:             { jp: 'ゲーム開発元が登録した見取り図です。ピンの色は人通りの多さ。',
                         en: 'The map the game developer registered. Pin colour is footfall.' },
  map_slot:            { jp: 'スロット',                      en: 'Slot' },
  map_eye_level:       { jp: 'スロットの目線写真',            en: 'The spot at eye level' },
  map_rules:           { jp: '入るサイズ',                    en: 'What fits here' },
  map_footfall:        { jp: '人通り（1 デモ時間あたり）',    en: 'Footfall (per demo hour)' },
  map_highest:         { jp: '現在の最高額',                  en: 'Highest bid' },
  map_closes:          { jp: '終了まで',                      en: 'Closes in' },
  map_per_1000:        { jp: '1,000 ビューあたり',            en: 'Credits per 1,000 views' },
  map_rating_rule:     { jp: 'レーティング条件',              en: 'Rating rule' },
  map_clock_waiting:   { jp: '最初の入札で 45 秒の時計が動きます',
                         en: 'Your first bid starts a 45-second clock' },
  map_no_fit:          { jp: 'あなたのコンテンツはここには入りません',
                         en: 'Your content does not fit here' },
  map_fits:            { jp: 'あなたのコンテンツが入ります',  en: 'Your content fits here' },
  map_footfall_low:    { jp: '人通り 少なめ',                 en: 'Lower footfall' },
  map_footfall_mid:    { jp: '人通り ふつう',                 en: 'Middling footfall' },
  map_footfall_high:   { jp: '人通り 多い',                   en: 'Busiest' },
  map_next_step:       { jp: 'この先（地域ごとの入札）は次のビルドで入ります',
                         en: 'Regions and bidding arrive in the next build' },
  map_no_content:      { jp: 'さきにコンテンツをアップロードしてください',
                         en: 'Upload a piece of content first' },

  // ---------------------------------------------------------------- housekeeping
  idle_resetting:      { jp: 'しばらく操作がないため、最初に戻ります',
                         en: 'Nobody here — going back to the start' },
  staff_reset:         { jp: 'スタッフ操作：リセットしました', en: 'Staff: reset' },
  staff_close:         { jp: 'スタッフ操作：オークションを締め切りました',
                         en: 'Staff: auction closed' },
  staff_corrupt:       { jp: 'スタッフ操作：壊れたパックを 1 回送ります',
                         en: 'Staff: one corrupted pack armed' },
  staff_freeze:        { jp: 'スタッフ操作：ダウンロードを 1 回止めます',
                         en: 'Staff: one frozen download armed' },
  error_server:        { jp: 'サーバーに届きませんでした',    en: 'The server did not answer' },
};

// Region names. The EN label is whatever the server's config says (so management material
// can switch to "Mock region 1"); the JP is looked up from it and simply left out if the
// label is one this table has never seen.
export const REGION_JP = {
  'Japan': '日本',
  'India': 'インド',
  'Europe': 'ヨーロッパ',
  'Mock region 1': '模擬地域 1',
  'Mock region 2': '模擬地域 2',
  'Mock region 3': '模擬地域 3',
};

// The server writes its own plain-English sentences (check details, rejection reasons, fit
// refusals) and it stays the authority on them — they are the same words the game client
// and the tests see. These patterns put a Japanese line above such a sentence. Anything
// with no pattern still gets a JP line: the generic one at the bottom.
const SENTENCE_RULES = [
  [/^Made for engine ([\d.]+) — this game runs ([\d.]+)\.$/,
    (m) => `エンジン ${m[1]} 用のファイルです — このゲームは ${m[2]} です。`],
  [/^Too tall for this slot — ([\d.]+) m against a ([\d.]+) m limit\.$/,
    (m) => `このスロットには高すぎます — ${m[1]} m、上限は ${m[2]} m。`],
  [/^Too wide for this slot — ([\d.]+) m against a ([\d.]+) m limit\.$/,
    (m) => `このスロットには広すぎます — ${m[1]} m、上限は ${m[2]} m。`],
  [/^Too deep for this slot — ([\d.]+) m against a ([\d.]+) m limit\.$/,
    (m) => `このスロットには奥行きがありすぎます — ${m[1]} m、上限は ${m[2]} m。`],
  [/^Fits this ([A-Z]) slot\.$/, (m) => `${m[1]} サイズのこのスロットに入ります。`],
  [/^up to ([\d.]+) x ([\d.]+) m on the ground and ([\d.]+) m tall$/,
    (m) => `地面 ${m[1]} × ${m[2]} m、高さ ${m[3]} m まで`],
  [/^built for engine ([\d.]+)$/, (m) => `エンジン ${m[1]} 用`],
  [/^rated (\w+)$/, (m) => `レーティング ${m[1]}`],
  [/^Fits size class ([A-Z]) \((.+)\)\.$/, (m) => `サイズクラス ${m[1]} に収まります（${m[2]}）。`],
  [/^Rated (\w+)\.$/, (m) => `レーティングは ${m[1]} です。`],
  [/^Rated (\w+) — this game allows (.+)\.$/,
    (m) => `レーティング ${m[1]} — このゲームが許可しているのは ${m[2]} です。`],
  [/^(\S+) (v\d+), (\d+) files, (.+), engine ([\d.]+)\.$/,
    (m) => `${m[1]} ${m[2]}・${m[3]} ファイル・${m[4]}・エンジン ${m[5]}。`],
  [/^Signed: (\d+) files, (.+), key (\w+)\.$/,
    (m) => `署名しました：${m[1]} ファイル・${m[2]}・鍵 ${m[3]}。`],
  [/^That file is not a \.dcpack/, () => '.dcpack ファイルとして読めませんでした。'],
  [/^This pack is (.+) — the limit is (.+)\.$/,
    (m) => `パックが大きすぎます：${m[1]}、上限は ${m[2]}。`],
];

export function japaneseFor(sentence) {
  if (!sentence) return '';
  const text = String(sentence).trim();
  for (const [pattern, make] of SENTENCE_RULES) {
    const m = text.match(pattern);
    if (m) return make(m);
  }
  return 'サーバーからの説明（英文）：';
}

export function t(key) {
  const entry = STRINGS[key];
  if (!entry) return { jp: key, en: key };
  return entry;
}
