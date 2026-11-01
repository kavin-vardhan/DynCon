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
  hint_step_25:        { jp: '± 25',                          en: '± 25' },
  hint_step_100:       { jp: '± 100',                         en: '± 100' },
  hint_place_bid:      { jp: '入札する',                      en: 'Place bid' },
  hint_raise:          { jp: '上乗せする',                    en: 'Raise' },
  hint_menu:           { jp: 'メニュー',                      en: 'Menu' },
  hint_push:           { jp: '更新を出す',                    en: 'Push an update' },
  hint_tick:           { jp: '選ぶ / やめる',                 en: 'Tick / untick' },

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
  map_no_content:      { jp: 'さきにコンテンツをアップロードしてください',
                         en: 'Upload a piece of content first' },

  // ---------------------------------------------------------------- 5 regions and bid
  regions_title:       { jp: '地域を選んで入札',              en: 'Regions and bid' },
  regions_sub:         { jp: '地域ごとに別のオークションです。入札が地域をまたいで比べられることはありません。',
                         en: 'Every region is its own auction — bids are never compared across regions.' },
  regions_region:      { jp: '地域',                          en: 'Region' },
  regions_footfall:    { jp: '人通り',                        en: 'Footfall' },
  regions_highest:     { jp: '現在の最高額',                  en: 'Highest' },
  regions_your_bid:    { jp: 'あなたの入札',                  en: 'Your bid' },
  regions_status:      { jp: '状態',                          en: 'Status' },
  regions_total:       { jp: '選んだ地域の合計',              en: 'Total across ticked regions' },
  regions_total_help:  { jp: '人通りで割り振ります',            en: 'Split by footfall' },
  regions_place:       { jp: '入札する',                      en: 'Place bid' },
  regions_min:         { jp: '次の入札額',                    en: 'Next bid' },
  regions_held_note:   { jp: '入札するとクレジットを確保します', en: 'A bid holds credits' },
  regions_pick_one:    { jp: '地域を 1 つ以上選んでください',  en: 'Tick at least one region' },
  regions_untick:      { jp: '選ぶ / やめる',                 en: 'Tick / untick' },
  status_leading:      { jp: 'あなたが最高額',                en: 'Leading' },
  status_outbid:       { jp: '上回られました',                en: 'Outbid' },
  status_idle:         { jp: '入札していません',              en: 'Not bidding' },
  status_will_bid:     { jp: 'これから入札',                  en: 'Will bid' },
  status_won:          { jp: '落札',                          en: 'Won' },
  status_lost:         { jp: '落とせず',                      en: 'Lost' },
  status_waiting:      { jp: '時計はまだ動いていません',      en: 'The clock has not started' },

  // ---------------------------------------------------------------- 6 auction
  auction_title:       { jp: 'オークション',                  en: 'Auction' },
  auction_sub:         { jp: '最初の入札で 45 秒。終了まぎわの入札は時計を 10 秒に戻します。',
                         en: '45 seconds from your first bid; a bid in the last 10 s puts the clock back to 10 s.' },
  auction_closes_in:   { jp: '終了まで',                      en: 'Closes in' },
  auction_outbid_in:   { jp: 'で上回られました',              en: 'Outbid in' },
  auction_soft_close:  { jp: '+10 秒',                        en: '+10 s' },
  auction_rival_once:  { jp: '相手の上乗せは 1 回だけです',   en: 'The rival raises once, then stops' },
  auction_raise:       { jp: 'この地域に上乗せ',              en: 'Raise this region' },
  auction_result:      { jp: '結果',                          en: 'Result' },
  auction_won:         { jp: '落札しました',                  en: 'Won' },
  auction_lost:        { jp: '落とせませんでした',            en: 'Lost' },
  auction_won_note:    { jp: 'このブロックはあなたのものです',
                         en: 'This block is yours' },
  auction_lost_note:   { jp: 'この地域は相手のコンテンツが出ます',
                         en: 'The rival’s content shows in this region' },
  auction_continue:    { jp: '次へ',                          en: 'Continue' },
  auction_charged:     { jp: '支払い',                        en: 'Charged' },

  // ---------------------------------------------------------------- 7 live
  live_title:          { jp: 'あなたのコンテンツが出ました',  en: 'Your content is live' },
  live_sub:            { jp: '公開ボタンはありません。プレイヤーが近づくと、ゲームが自分で取りに行きます。',
                         en: 'There is no publish button — the game fetches it when a player comes near.' },
  live_step_alloc:     { jp: '割り当て',                      en: 'Resolve' },
  live_step_alloc_sub: { jp: '署名付きで返します',              en: 'Signed manifest, server side' },
  live_step_download:  { jp: 'ダウンロード',                  en: 'Download' },
  live_step_dl_sub:    { jp: 'プレイヤーの PC で',              en: 'On the player’s machine' },
  live_step_verify:    { jp: '検証',                          en: 'Verify' },
  live_step_verify_sub:{ jp: '署名とハッシュ',                  en: 'Signature, then hashes' },
  live_step_mount:     { jp: 'マウント',                      en: 'Mount' },
  live_step_mount_sub: { jp: 'ゲームからの報告',                en: 'Reported by the game' },
  live_waiting:        { jp: 'プレイヤーが近づくのを待っています',
                         en: 'Waiting for a player to come near the slot' },
  live_marker:         { jp: 'プレイヤーの画面にはそこへのマーカーが出ます',
                         en: 'The player’s screen shows a marker to it' },
  live_ends_in:        { jp: 'このブロックの残り',            en: 'This block ends in' },
  live_regions_now:    { jp: 'いま地域ごとに出ているもの',    en: 'What each region shows now' },
  live_to_report:      { jp: 'レポートを見る',                en: 'See the report' },

  // ---------------------------------------------------------------- 8 region check
  menu_title:          { jp: 'メニュー',                      en: 'Menu' },
  menu_preview:        { jp: 'プレビュー画面の地域',          en: 'The preview window’s region' },
  menu_preview_help:   { jp: '同じゲームの 2 本目を、別の地域のプレイヤーとして動かします',
                         en: 'The second copy of the same game, as a player in another region' },
  menu_pause:          { jp: 'キャンペーンを一時停止',        en: 'Pause the campaign' },
  menu_resume:         { jp: 'キャンペーンを再開',            en: 'Resume the campaign' },
  menu_summary:        { jp: 'まとめを見る',                  en: 'See the summary' },
  menu_close:          { jp: '閉じる',                        en: 'Close' },
  menu_hint:           { jp: 'メニュー',                      en: 'Menu' },

  // ---------------------------------------------------------------- 9 report
  report_title:        { jp: 'レポート',                      en: 'Report' },
  report_sub:          { jp: '地域ごとの結果です。ビューはシミュレーションと実測を分けて出しています。',
                         en: 'Per region. Views are simulated footfall and really counted views, kept apart.' },
  report_views:        { jp: 'ビュー',                        en: 'Views' },
  report_simulated:    { jp: 'シミュレーション',              en: 'simulated' },
  report_live_counted: { jp: '実測',                          en: 'counted' },
  report_visits:       { jp: '入場',                          en: 'Visits' },
  report_dwell:        { jp: '滞在',                          en: 'Dwell' },
  report_interactions: { jp: '操作',                          en: 'Interactions' },
  report_charged:      { jp: '支払い',                        en: 'Charged' },
  report_per_1000:     { jp: '1,000 ビューあたり',            en: 'Per 1,000 views' },
  report_time_left:    { jp: 'このブロックの残り',            en: 'Time left in this block' },
  report_pause:        { jp: '一時停止',                      en: 'Pause' },
  report_resume:       { jp: '再開',                          en: 'Resume' },
  report_paused:       { jp: '一時停止中 — ゲーム側の標準が出ています',
                         en: 'Paused — the game’s own content is showing' },
  report_push:         { jp: '更新を出す',                    en: 'Push an update' },
  report_book_next:    { jp: '次のブロックを予約',            en: 'Book the next block' },
  report_totals:       { jp: '合計',                          en: 'Totals' },
  report_nothing:      { jp: 'まだ何も動いていません',        en: 'Nothing running yet' },

  // ---------------------------------------------------------------- 10 push an update
  update_title:        { jp: '更新を出す',                    en: 'Push an update' },
  update_sub:          { jp: '公開中のコンテンツのバージョン 2 です。プレイヤーの邪魔はしません。',
                         en: 'Version 2 of what is live — without interrupting anybody.' },
  update_step_ok:      { jp: '承認',                          en: 'Approved' },
  update_step_serving: { jp: 'プラットフォームが v2 を配信',  en: 'The platform is serving v2' },
  update_step_swapped: { jp: 'ゲームが入れ替えました',        en: 'The game swapped it' },
  update_inside:       { jp: 'プレイヤーが中にいるあいだは切り替わりません。出たら入れ替わります。',
                         en: 'If the player is inside, nothing changes until they walk out — then it swaps.' },
  update_swapped:      { jp: '入れ替わりました — 照明・ドア・画面はそのままです',
                         en: 'Swapped — lights, door and screen kept as they were' },
  update_back:         { jp: 'レポートに戻る',                en: 'Back to the report' },
  update_version:      { jp: '公開中',                        en: 'Live now' },

  // ---------------------------------------------------------------- 11 summary
  summary_title:       { jp: 'このブロックのまとめ',          en: 'This block' },
  summary_sub:         { jp: 'ブロックが終わり、次の落札者に入れ替わりました。',
                         en: 'The block ended and the next winner swapped in.' },
  summary_spent:       { jp: '使ったクレジット',              en: 'Credits spent' },
  summary_cost_view:   { jp: '1 ビューあたり',                en: 'Cost per view' },
  summary_reset_in:    { jp: '最初に戻るまで',                en: 'Starting over in' },
  summary_now:         { jp: 'いますぐ最初に戻る',            en: 'Start over now' },

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

const AXIS_JP = { tall: '高すぎます', wide: '広すぎます', deep: '奥行きがありすぎます' };

/** A region's Japanese name inside a sentence the server wrote in English. */
function jpRegion(label) {
  return REGION_JP[label] ? `${REGION_JP[label]}` : label;
}

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
  // the auction's own sentences
  [/^Leading in (.+) at (\d+) — (\d+) s left\.$/,
    (m) => `${jpRegion(m[1])}で ${m[2]} のトップです — 残り ${m[3]} 秒。`],
  [/^Leading in (.+) at (\d+)\.$/, (m) => `${jpRegion(m[1])}で ${m[2]} のトップです。`],
  [/^(.+) is at (\d+) \(the rival holds it\), so the next bid is (\d+)\.$/,
    (m) => `${jpRegion(m[1])}は ${m[2]}（相手が保持）なので、次の入札は ${m[3]} からです。`],
  [/^(.+) is at (\d+) \(you hold it\), so the next bid is (\d+)\.$/,
    (m) => `${jpRegion(m[1])}は ${m[2]}（あなたが保持）なので、次の入札は ${m[3]} からです。`],
  [/^(.+)'s auction for this slot has closed\.$/,
    (m) => `このスロットの${jpRegion(m[1])}のオークションは終わりました。`],
  [/^You have (\d+) credits available and this bid needs (\d+) more\.$/,
    (m) => `使えるクレジットは ${m[1]} で、この入札にはあと ${m[2]} 必要です。`],
  [/^That is not one of your uploads\.$/, () => 'それはあなたがアップロードしたものではありません。'],
  [/^That content has no approved version yet\.$/, () => 'そのコンテンツにはまだ承認済みのバージョンがありません。'],
  [/^(\S+) does not fit slot (\S+) — too (\w+), (.+)\.$/,
    (m) => `${m[1]} はスロット ${m[2]} に入りません — ${AXIS_JP[m[3]] || m[3]}、${m[4]}。`],
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
