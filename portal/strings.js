// Every word the portal can put on screen, in one table.
//
// **English only** — Kavin's ruling, 2026-11-02. The demo used to draw every line twice,
// Japanese over English; a machine-drafted Japanese line that nobody had reviewed was
// judged too risky to show at the booth, so it is gone. Plan v6 §10 item 4 still says
// "every string in JP and EN"; this file is the override, and `specs/DECISIONS.md` records
// it. The table itself stays: a professionally translated language can be added here later
// without touching a single screen.
//
// Rules this table keeps, from CLAUDE.md rule 3 and specs/portal_spec_v1.md §1:
//   * one entry per thing the portal can say, keyed, so every screen reads from one place.
//   * no game titles, no studio or brand names, no real money words. "Game A" / "Game B",
//     slots A1-B2, "another brand" for the rivals, and credits are always labelled
//     "demo credits - not real money".
//   * "Dynamic Contents" is the platform's own wordmark, not a brand in the tour, so it is
//     the one proper noun allowed here.

export const STRINGS = {
  // ---------------------------------------------------------------- chrome
  app_name:            'Dynamic Contents',
  your_brand:          'Your brand',
  wallet_available:    'Available',
  wallet_held:         'Held',
  wallet_charged:      'Charged',
  demo_credits_note:   'demo credits — not real money',
  clock_label:         'demo time',
  pad_offline:         'No pad — keyboard works',

  // ---------------------------------------------------------------- button hints
  hint_move:           'Move',
  hint_select:         'Select',
  hint_back:           'Back',
  hint_start:          'Start',
  hint_upload:         'Upload',
  hint_next:           'Continue',
  hint_pick_slot:      'Hop between slots',
  hint_bid:            'Go to bidding',
  hint_step_25:        '± 25',
  hint_step_100:       '± 100',
  hint_place_bid:      'Place bid',
  hint_raise:          'Raise',
  hint_menu:           'Menu',
  hint_push:           'Push an update',
  hint_tick:           'Tick / untick',

  // ---------------------------------------------------------------- 0 attract
  attract_tagline:     'Content in the slots of a live game — no patch, no restart',
  attract_now_showing: 'On the slots right now',
  attract_auctions:    'Auctions running now',
  attract_start:       'Press A to start',
  attract_role:        'You take the brand’s seat',
  showing_rival:       'Another brand',
  showing_default:     'The game’s own',
  showing_you:         'Your content',
  showing_none:        'Empty',
  holder_rival:        'Another brand leads',
  holder_you:          'You lead',

  // ---------------------------------------------------------------- 1 brand
  brand_title:         'Create your brand',
  brand_sub:           'Pick a colour and an emblem. They go on your content’s sign.',
  brand_colours:       'Colour',
  brand_emblems:       'Emblem',
  brand_preview:       'Sign preview',
  brand_confirm:       'Use this brand',
  brand_wallet:        'You have 2,000 demo credits',
  brand_no_names:      'No names anywhere — a colour and an emblem are your whole identity.',

  // ---------------------------------------------------------------- 2 upload
  upload_title:        'Upload your content',
  upload_your_computer:'Your computer',
  upload_pick:         'Choose a file and press A',
  upload_reading:      'Reading from your computer',
  upload_sending:      'Uploading',
  upload_checking:     'The platform is checking it',
  upload_checks:       'The four checks',
  check_package:       'Package',
  check_rating:        'Rating',
  check_fit:           'Fit',
  check_sign:          'Sign',
  check_waiting:       'Waiting',
  check_skipped:       'Did not run',
  upload_approved:     'Approved',
  upload_rejected:     'Rejected',
  upload_my_content:   'My content',
  upload_again:        'Try another file',
  upload_continue:     'Pick a game',
  upload_size_class:   'Size class',
  upload_bounds:       'Measured size',
  upload_fits_in:      'Fits these slots',
  upload_file_note:    'This file is built to fail',
  upload_empty:        'Nothing yet',
  upload_failed:       'That upload did not go through',

  // ---------------------------------------------------------------- 3 games
  games_title:         'Pick a game',
  games_sub:           'One piece of content, any game on the platform',
  games_slots:         'Dynamic slots',
  games_players:       'Players online',
  games_badge_booth:   'Playing at this booth',
  games_registered:    'Slot map registered by the developer',

  // ---------------------------------------------------------------- 4 slot map
  map_title:           'Slot map',
  map_sub:             'The map the game developer registered. Pin colour is footfall.',
  map_slot:            'Slot',
  map_eye_level:       'The spot at eye level',
  map_rules:           'What fits here',
  map_footfall:        'Footfall (per demo hour)',
  map_highest:         'Highest bid',
  map_closes:          'Closes in',
  map_per_1000:        'Credits per 1,000 views',
  map_rating_rule:     'Rating rule',
  map_clock_waiting:   'Your first bid starts a 45-second clock',
  map_no_fit:          'Your content does not fit here',
  map_fits:            'Your content fits here',
  map_footfall_low:    'Lower footfall',
  map_footfall_mid:    'Middling footfall',
  map_footfall_high:   'Busiest',
  map_no_content:      'Upload a piece of content first',

  // ---------------------------------------------------------------- 5 regions and bid
  regions_title:       'Regions and bid',
  regions_sub:         'Every region is its own auction — bids are never compared across regions.',
  regions_region:      'Region',
  regions_footfall:    'Footfall',
  regions_highest:     'Highest',
  regions_your_bid:    'Your bid',
  regions_status:      'Status',
  regions_total:       'Total across ticked regions',
  regions_total_help:  'Split by footfall',
  regions_place:       'Place bid',
  regions_min:         'Next bid',
  regions_held_note:   'A bid holds credits',
  regions_pick_one:    'Tick at least one region',
  regions_untick:      'Tick / untick',
  status_leading:      'Leading',
  status_outbid:       'Outbid',
  status_idle:         'Not bidding',
  status_will_bid:     'Will bid',
  status_won:          'Won',
  status_lost:         'Lost',
  status_waiting:      'The clock has not started',

  // ---------------------------------------------------------------- 6 auction
  auction_title:       'Auction',
  auction_sub:         '45 seconds from your first bid; a bid in the last 10 s puts the clock back to 10 s.',
  auction_closes_in:   'Closes in',
  auction_outbid_in:   'Outbid in',
  auction_soft_close:  '+10 s',
  auction_rival_once:  'The rival raises once, then stops',
  auction_raise:       'Raise this region',
  auction_result:      'Result',
  auction_won:         'Won',
  auction_lost:        'Lost',
  auction_won_note:    'This block is yours',
  auction_lost_note:   'The rival’s content shows in this region',
  auction_continue:    'Continue',
  auction_charged:     'Charged',

  // ---------------------------------------------------------------- 7 live
  live_title:          'Your content is live',
  live_sub:            'There is no publish button — the game fetches it when a player comes near.',
  live_step_alloc:     'Resolve',
  live_step_alloc_sub: 'Signed manifest, server side',
  live_step_download:  'Download',
  live_step_dl_sub:    'On the player’s machine',
  live_step_verify:    'Verify',
  live_step_verify_sub:'Signature, then hashes',
  live_step_mount:     'Mount',
  live_step_mount_sub: 'Reported by the game',
  live_waiting:        'Waiting for a player to come near the slot',
  live_marker:         'The player’s screen shows a marker to it',
  live_ends_in:        'This block ends in',
  live_regions_now:    'What each region shows now',
  live_to_report:      'See the report',

  // ---------------------------------------------------------------- 8 region check
  menu_title:          'Menu',
  menu_preview:        'The preview window’s region',
  menu_preview_help:   'The second copy of the same game, as a player in another region',
  menu_pause:          'Pause the campaign',
  menu_resume:         'Resume the campaign',
  menu_summary:        'See the summary',
  menu_flip:           'Play the main game as this region',
  menu_close:          'Close',
  menu_hint:           'Menu',
  // The empty rectangle the preview window covers while this step is open. The window is
  // another program, so the portal can only leave room for it and say what belongs there.
  preview_window_here: 'The preview window appears here',
  preview_window_missing: 'The preview window is not running',

  // ---------------------------------------------------------------- 9 report
  report_title:        'Report',
  report_sub:          'Per region. Views are simulated footfall and really counted views, kept apart.',
  report_views:        'Views',
  report_simulated:    'simulated',
  report_live_counted: 'counted',
  report_visits:       'Visits',
  report_dwell:        'Dwell',
  report_interactions: 'Interactions',
  report_charged:      'Charged',
  report_per_1000:     'Per 1,000 views',
  report_time_left:    'Time left in this block',
  report_pause:        'Pause',
  report_resume:       'Resume',
  report_paused:       'Paused — the game’s own content is showing',
  report_push:         'Push an update',
  report_book_next:    'Book the next block',
  report_totals:       'Totals',
  report_nothing:      'Nothing running yet',

  // ---------------------------------------------------------------- 10 push an update
  update_title:        'Push an update',
  update_sub:          'Version 2 of what is live — without interrupting anybody.',
  update_step_ok:      'Approved',
  update_step_serving: 'The platform is serving v2',
  update_step_swapped: 'The game swapped it',
  update_inside:       'If the player is inside, nothing changes until they walk out — then it swaps.',
  update_swapped:      'Swapped — lights, door and screen kept as they were',
  update_back:         'Back to the report',
  update_version:      'Live now',

  // ---------------------------------------------------------------- 11 summary
  summary_title:       'This block',
  summary_sub:         'The block ended and the next winner swapped in.',
  summary_spent:       'Credits spent',
  summary_cost_view:   'Cost per view',
  summary_reset_in:    'Starting over in',
  summary_now:         'Start over now',

  // ---------------------------------------------------------------- housekeeping
  idle_resetting:      'Nobody here — going back to the start',
  staff_reset:         'Staff: reset',
  staff_close:         'Staff: auction closed',
  staff_corrupt:       'Staff: one corrupted pack armed',
  staff_freeze:        'Staff: one frozen download armed',
  error_server:        'The server did not answer',
};

// The region names this build knows. A screen always draws the label the *server* sends
// (`/config/public`, `/lots`, `/report`), because the booth's region names live in
// `server/config/demo.json` and management material swaps them for the neutral ones
// (CLAUDE.md rule 3). This list is the other half of that contract: it is every name the
// portal has been written for, and `server/tests/test_preview.py` fails if the config ever
// names a region that is not here. When a translated language is added, this is where the
// per-region words go.
export const REGION_LABELS = [
  'Japan',
  'India',
  'Europe',
  'Mock region 1',
  'Mock region 2',
  'Mock region 3',
];

/** One string from the table, or the key itself if this build has never heard of it. */
export function t(key) {
  const entry = STRINGS[key];
  return entry === undefined ? key : entry;
}
