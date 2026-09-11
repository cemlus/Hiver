# Intent taxonomy (v1, 2026-09-11)

> **Taxonomy FROZEN (v1, 2026-09-11): 11 intents and 4 conversation states. The escalation policy is still a DRAFT: it will be calibrated on the 40-item dev set, then frozen. The 200-item golden set is not sampled or labelled until both are frozen.** Rendered by `scripts/taxonomy_explore.py render` from `data/taxonomy/taxonomy_v1.yaml` and `data/taxonomy/discovery_sample_coding.csv`. The labeller-facing codebook is `data/codebook.md`. No classifier exists yet.

> **Evidence status.** The 150 exchanges in `data/taxonomy/discovery_sample_coding.csv` are **taxonomy discovery evidence, not the evaluation gold set.** One person (the assistant, while drafting) coded them to find and size candidate intents. They come from the **train** split, so they can never enter dev or golden. The golden set will be sampled from the holdout split and labelled against the frozen codebook. Counts derived from this sample are rough estimates.

**How this was built.**
- **Open coding.** 150 random train exchanges were read with their conversation context. Each got a conversation state and, where there was a support request, the intent whose response and escalation strategy fits. A runner-up was noted where one was plausible, and secondary issues where a message raised two.
- **Exploratory topics.** NMF topics over train first contacts (`results/taxonomy/topics.md`) were used only to check that no frequent theme was missed.
- **Examples.** Extra examples for rare intents came from regex searches over train, read by hand.

**Final changes before the freeze.**
- S1 now requires that **no unresolved support issue remains** for `acknowledgement_closing`. 'Will try tonight' and 'I'll get back to you' are `issue_followup`. This moved one sampled exchange (O048).
- A new internal-only field, `secondary_intents`, keeps the other issue(s) of a multi-issue message. T0 picks the one primary intent that is scored.
- `product_info_feedback` stays merged. Controllers stay inside `hardware_devices` as an internal subtype.
- `subtype`, `event_tag` and `secondary_intents` are internal and never scored.

## Final table (v1)

Estimates are `k / 150 × 12,792` train exchanges (95% Wilson range); the sample is too small to resolve intents under ~2%. 133 of the 150 sampled exchanges carry an intent; the rest are closing or social messages (see conversation states). Default risk and escalation are a separate layer and are still DRAFT.

| intent | definition | include | exclude | est. train count (95% range) | response strategy | default risk | default escalation | top confusable (seen in coding) |
|---|---|---|---|---|---|---|---|---|
| `connectivity_xbox_live` | The customer can't reach Xbox Live or a game's online service, or their online session is unstable: service sign-in, disconnects, lag, NAT, party chat connection, game servers, or 'is Live down?'. | Xbox Live or game servers down, unreachable or 'failed to allocate'; outage and status questions; Disconnects, lag, NAT type, lobby or matchmaking failures; Party chat that won't connect, drops people, or has no audio because of connection or privacy settings; Network errors during setup (can't get online) | Credential problems (forgotten password, recovery, account creation) → `account_access_profile`; 'Can't play online, it says I need Gold' → `entitlements_subscriptions_codes`; An app or game misbehaving while online works, and party menu/UI glitches → `software_game_app` | ≈ 1,020 (590 – 1,720) | Check for a known outage first and point to the status page. Otherwise give network troubleshooting: power cycle the console and router, check NAT and detailed network stats, wired vs Wi-Fi. | low | auto | `software_game_app` (6), `account_access_profile` (4), `entitlements_subscriptions_codes` (0) |
| `install_download_update` | Getting software onto the console fails or stalls: game or app downloads and installs, disc installs, system updates, storage, or content that has to be re-downloaded. | 'Installation stopped', downloads stuck or slow, queue problems; Console or game updates that fail, loop or error; Games deleted or needing reinstall after an update; storage-full errors; Disc games that won't install | Installed content that crashes or won't start → `software_game_app`; Owned content the store won't let the customer get → `entitlements_subscriptions_codes`; The disc drive not reading any disc → `hardware_devices` | ≈ 1,020 (590 – 1,720) | Give install and update troubleshooting (clear local storage, offline system update, cancel and reinstall, check storage and the queue), or point to a known publisher-side issue. | low | auto | `software_game_app` (3), `product_info_feedback` (1) |
| `hardware_devices` | A physical device misbehaves: console power, shutdowns, heat or noise, disc drive, display/HDMI, controllers, headsets, Kinect, external storage. Also repair, warranty and replacement. Controllers stay here; their subtype is internal. | Console won't power on, shuts down, has no signal, green dots, fan noise; Disc drive won't read discs or scratches them; Blu-ray playback errors that point at the drive; Controllers that won't pair, disconnect, desync, or have faulty buttons; headset and mic problems; External drives not detected; device registration and warranty | One game or app freezing while everything else works → `software_game_app`; Wrong item in the box, delivery or retailer problems → `purchases_billing_orders` | ≈ 1,620 (1,060 – 2,420) | Give device troubleshooting (power cycle, another outlet, re-pair and update the controller, check the drive). If the device is faulty, route to the online repair or replacement process. | medium | auto → escalate for repair | `software_game_app` (4), `purchases_billing_orders` (3) |
| `software_game_app` | Installed software misbehaves: a game or app crashes, won't launch or has a bug; dashboard/UI problems after an update; app features such as notifications, messaging, streaming and achievements. Merged for v1. | A specific game or app crashes, freezes, won't open, or shows an error code; Dashboard/Guide UI broken or slow after an update; notifications, messages, keyboard; Achievements not unlocking; in-game content or credits missing because of a bug; Store or Xbox app crashing (the app itself, not a purchase) | Download or installation failures → `install_download_update`; Can't reach Live or game servers → `connectivity_xbox_live`; Paid content missing → `entitlements_subscriptions_codes` | ≈ 2,220 (1,550 – 3,090) | Give app or game troubleshooting (power cycle, remove and re-add the profile, uninstall and reinstall, check whether the console is in the Insider preview). Point to the developer or publisher for game-side bugs and patches. | low | auto | `connectivity_xbox_live` (6), `hardware_devices` (4), `install_download_update` (3) |
| `account_access_profile` | The customer's Microsoft/Xbox account itself: signing in with their credentials, recovery, creation, email/alias, gamertag, child/adult and family settings, profile data. A compromised account is this intent, with the SECURITY risk rule on top. | Can't sign in to *my* account, password or email recovery, account creation errors; Gamertag changes and availability, email alias, tenure or profile data; Child account rules and family settings; Account hacked or used by someone else (the SECURITY rule applies) | Service-wide sign-in outages → `connectivity_xbox_live`; Home Xbox and licences → `entitlements_subscriptions_codes`; Another player's conduct → `enforcement_safety` | ≈ 770 (410 – 1,410) | Link the self-service guide (recovery, alias, gamertag, family settings). Fixes that touch the customer's own account need identity verification, so hand off to chat or phone support. | medium | escalate if account-specific | `connectivity_xbox_live` (4), `entitlements_subscriptions_codes` (3) |
| `purchases_billing_orders` | The money or the order: purchases that fail, unexpected or duplicate charges, refunds, pricing and sales, pre-order deliveries, wrong items, retailer problems. Kept separate from entitlements. | Purchase fails with a payment error; payment method problems; Charged twice or unexpectedly; refund requests; sale price not honoured; Pre-order delivery or shipment; wrong item in the box; retailer issues | Paid, but the game, membership or code isn't showing → `entitlements_subscriptions_codes` (T5); Policy questions with no problem ('why does a free game need a card?') → `product_info_feedback` | ≈ 600 (290 – 1,190) | Acknowledge, share generic tips if relevant (check the payment info, try the web store), then route charges, refunds and orders to billing/chat support, and retailer orders to the retailer. | high | escalate | `entitlements_subscriptions_codes` (5), `hardware_devices` (3) |
| `entitlements_subscriptions_codes` | Something the customer is entitled to isn't recognised or delivered: Gold / Game Pass memberships and trials, code or gift-card redemption, DLC and pre-order bonuses, owned games missing, licences, Home Xbox, game sharing. Merged for v1. | Gold or Game Pass bought or active but not recognised; trial questions; Codes or gift cards that won't redeem; beta or early-access codes; Pre-order bonuses, DLC or season-pass items, or purchased games missing from the library; Home Xbox changes, game sharing, licences for owned games | Payment failures, double charges, refunds → `purchases_billing_orders`; Bare error codes unrelated to redemption → `software_game_app` / `connectivity_xbox_live` | ≈ 1,190 (720 – 1,930) | Give entitlement troubleshooting (check subscriptions and order history, remove and re-add the profile, power cycle, follow the redemption guide). Hand off if it's still missing. | medium | auto → escalate if still missing | `purchases_billing_orders` (5), `account_access_profile` (3), `connectivity_xbox_live` (0) |
| `enforcement_safety` | Suspensions, bans and enforcement messages; reports of other players' conduct (harassment, threats, cheating); code-of-conduct questions; content rejected by moderation. | 'Why was I banned or suspended?', appeals, enforcement notices; Reporting another player, harassment, 'why wasn't action taken?'; Rejected gamerpics or content; code-of-conduct questions | The customer's own account being hacked → `account_access_profile`; Anger at support with no enforcement topic → `support_process_complaint` | ≈ 510 (240 – 1,080) | Use the fixed policy reply: support can't discuss or influence enforcement; point to the enforcement site and case review, and explain how to report players. Never speculate about an outcome. | medium | auto (policy) | `support_process_complaint` (1) |
| `product_info_feedback` | Questions about how things work or what's available, and feedback or feature requests: specs, compatibility, backward compatibility, setup, how-tos, availability, policies, suggestions, negative opinions on design or updates. Questions and feedback stay merged. | How-to and 'does X support Y' questions (1080p streaming, external SSD, setup without internet); Backward-compatibility and content availability requests; Feature requests and negative opinions on design or updates; Policy questions (why a payment method is needed, trial limits in general) | The customer reports that something is failing → the matching issue intent (T10); Praise with no request → `social_offtopic` state (S2) | ≈ 1,280 (790 – 2,030) | Answer the factual question from the knowledge base. For suggestions, thank the customer and point to the feedback site. Never speculate on release dates or the roadmap. | low | auto | `install_download_update` (1) |
| `support_process_complaint` | The message is mainly about the support experience, not a product problem: unanswered or repeated contacts, rude or unhelpful agents, demands for a human or another channel, general 'no one helps'. | 'Still waiting for help', 'chatted 4 times, still no solution'; Complaints about an agent or phone support; 'are you going to help me or not?'; Asks for another channel because the offered one doesn't work for them | A complaint that names a concrete product issue → that issue's intent, with the REPEAT_CONTACT / HIGH_ANGER risk rules; Anger about bans → `enforcement_safety` (T8); Vague help requests without a complaint about support → `needs_more_context` (T9) | ≈ 510 (240 – 1,080) | Apologise, acknowledge the history, ask for the one missing detail or offer the right channel, and hand the case to a person. | high | escalate | `needs_more_context` (4), `enforcement_safety` (1) |
| `needs_more_context` | Even with the available thread context, the support issue can't be determined confidently enough to act. | A bare help request, image or link only: 'Any ideas or help? <URL>', 'Hello? Need assistance'; 'Having the same issues too' with no thread to inherit from; A pointer to an earlier question that isn't in the data; frustration with a screenshot only | Follow-ups whose issue is in the context → the thread's intent (`issue_followup`); Complaints about support itself → `support_process_complaint` (T9) | ≈ 600 (290 – 1,190) | Ask exactly one targeted clarifying question that names the missing detail (e.g. 'Which console, and what exact error text do you see?'). Never send a generic reply or a guess. | low | auto (one clarifying question) | `support_process_complaint` (4) |

## Conversation states

Every exchange gets a state. Only `new_issue` and `issue_followup` carry a primary intent; the other two sit outside the intent benchmark and are scored as state accuracy.

| state | carries an intent | definition | in sample | est. train count (95% range) | strategy |
|---|---|---|---|---|---|
| `new_issue` | yes | The message raises a support issue this customer hasn't already raised in this thread. This includes replies to brand announcements and to other customers' tweets. | 99 / 150 | ≈ 8,440 (7,430 – 9,350) | Handled by its intent. |
| `issue_followup` | yes | The message continues a support issue this customer already raised in the thread, or answers the brand about it: details, 'tried that', 'still broken', 'are you going to help?'. Promises to try something or report back ('will try tonight', 'I'll get back to you') are also follow-ups, because the issue is still open. It takes the thread's issue as its intent. | 34 / 150 | ≈ 2,900 (2,140 – 3,840) | Handled by its intent. The reply must use the context, and must not repeat steps the customer says they've tried. |
| `acknowledgement_closing` | no | The customer thanks the brand, confirms the issue is fixed, or says okay, **and no unresolved support issue remains**. Nothing new is asked, and nothing is pending on the customer's side. | 9 / 150 | ≈ 770 (410 – 1,410) | A short close-the-loop reply offering further help. No troubleshooting, no retrieval. |
| `social_offtopic` | no | No support request at all: praise, banter, self-promotion, tweets that only tag the brand. | 8 / 150 | ≈ 680 (350 – 1,300) | A short friendly reply (or none). No troubleshooting, no retrieval. |

**S1 made explicit:** `acknowledgement_closing` requires that no unresolved support issue remains.

| customer says | state | why |
|---|---|---|
| "Thanks, it works now" | `acknowledgement_closing` | Resolved; nothing open |
| "Everything is fixed" | `acknowledgement_closing` | Resolved; nothing open |
| "Okay, thank you" | `acknowledgement_closing` | Nothing asked, nothing pending |
| "Will try tonight" | `issue_followup` | The fix hasn't been tried: the issue is still open |
| "I'll try that and let you know" | `issue_followup` | Outcome pending: the issue is still open |
| "I'll get back to you" | `issue_followup` | Outcome pending: the issue is still open |

**`new_issue` examples**

- `332201` · first contact
  - **customer:** error 0x800c0005 when joining any party I have open nat wired connection and fully rebooted everything
- `903420` · first contact
  - **customer:** Guys I'm having major issues installing games on my Xbox One, Keep getting Installation stopped, but there's space on drive
- `2244439` · first contact
  - **customer:** My Project Scorpio isn't reading any discs....what do I need to do to get a replacement

**`issue_followup` examples**

- `1068162` · first contact
  - _customer_: been sitting here watching my game not start for over an hour. Little help here.
  - _other_customer_: Not gonnalie... think it is a @user @user issue not @user
  - **customer:** Can open any other game other than FIFA 18??
- `1848043` · first contact
  - _customer_: My Forza Horizon 3 screen freeze a lot. Why? Digital version
  - **customer:** Guys...? Please help
- `1376956` · follow-up
  - _customer_: well I was enjoying #Madden18 on the daily but unfortunately today my Xbox died and I'll have to miss out 😥😥
  - _customer_: Yes 3 to be exact
  - _brand_: Thanks for that info. Is your console currently powering on, but displaying a blank screen?
  - **customer:** The tv displays no signal
- `866890` · follow-up
  - _customer_: I downloaded the new Xbox a couple days ago and when download a game if I click on a game or app, it stops the download. Help!
  - _brand_: Hi there! Would you mind sending a picture of your network stats: Settings>Network>Network Settings>Detailed Network Statistics and your NAT on the console?
  - **customer:** I’ll do that tonight, was busy with school yesterday. Sorry about that!

**`acknowledgement_closing` examples**

- `1523187` · follow-up
  - _customer_: hello my xbox just signed me out and wont let me back in please help !!!
  - _brand_: Hi there! Let's have you try resetting your router/modem and then power cycle: <URL>
  - **customer:** thank you i did a power cycle and now everything is back on fine 👍🏼👍🏼
- `831330` · follow-up
  - _customer_: hello my xbox has been very slow. it work last night but my xbox updated and made it very slow
  - _brand_: Hello! Would you mind following us and sending a DM when you are so we can gather more info?
  - **customer:** oh sorry for the worry everything seem to to work now
- `2124069` · follow-up
  - _brand_: Have an Xbox support question & haven't heard back from us yet? Send another tweet our way if you need help!
  - _customer_: Hi, so I run into this big problem with my external hard drive ... since I have the X and plugged in my external hard drive it detected wel, not the issue here. But when I start a game that is on there it will shut of a…
  - _brand_: Hey there! Can you follow & DM us your Gamertag? Also, is it your console that is shutting off or your external hard drive? Any pictures you can share would be very helpful!
  - **customer:** I've just been helped and I think its fixed, I let you guys know if I run into the same problem. Another usb port on my xbox one x does the job (for now at least) but lets be positive. :)
- `1111772` · follow-up
  - _customer_: will war for the planet of the apes come to the Xbox store in UHD?
  - _customer_: Like 4k...Some movies you can buy in 4k. Like Kong or Wonder woman. So just wondering if planet of the apes will be available in 4k? (:
  - _brand_: Apologies for the confusion. We wouldn't be able to speculate if it will or not. Keep an eye on the store for news.
  - **customer:** Okay..thank you

**`social_offtopic` examples**

- `2006809` · first contact
  - **customer:** Huge kudos to @user @user @user @user @user and everyone else on the latest #XboxOne dashboard update. It's awesome!
- `295529` · first contact
  - **customer:** Thanks to my top interactors! Have a lovely weekend :-) @user
- `2380329` · follow-up
  - _customer_: I am so frustrated! Constant lag and disconnects. What is going on Sledgehammer Games!!! @user
  - _customer_: How unfortunate. I wish I can refund this game because I am having nothing but problems! Can I please get a refund on Call of Duty: WWII? I am having nothing but issues. Lag, disconnects, etc. PLEASE.
  - _brand_: Hello! For refund inquiries, you will need to reach out chat support here: <URL> for more info.
  - **customer:** I like your new profile picture

## 1. `connectivity_xbox_live`

**Definition.** The customer can't reach Xbox Live or a game's online service, or their online session is unstable: service sign-in, disconnects, lag, NAT, party chat connection, game servers, or 'is Live down?'.

**Include**
- Xbox Live or game servers down, unreachable or 'failed to allocate'; outage and status questions
- Disconnects, lag, NAT type, lobby or matchmaking failures
- Party chat that won't connect, drops people, or has no audio because of connection or privacy settings
- Network errors during setup (can't get online)

**Exclude**
- Credential problems (forgotten password, recovery, account creation) → `account_access_profile`
- 'Can't play online, it says I need Gold' → `entitlements_subscriptions_codes`
- An app or game misbehaving while online works, and party menu/UI glitches → `software_game_app`

**Response strategy.** Check for a known outage first and point to the status page. Otherwise give network troubleshooting: power cycle the console and router, check NAT and detailed network stats, wired vs Wi-Fi.

**Default risk.** `low`. **Default escalation (draft).** Auto (ROUTINE_TROUBLESHOOTING, or GENERAL_INFO for outages). Escalate on REPEAT_CONTACT when the standard steps have already failed.

**Estimated training count.** ≈ 1,020 (95% range 590 – 1,720; 12 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `software_game_app` (6), `account_access_profile` (4), `entitlements_subscriptions_codes` (0)

**Representative examples** (train; context shown where present):

- `332201` · first contact
  - **customer:** error 0x800c0005 when joining any party I have open nat wired connection and fully rebooted everything
- `2196917` · first contact
  - **customer:** Hey, Any ideas why i'm still having major lobby issues on XB1? Wired connection Nat type 2 (open) what else can I do.
- `1529692` · first contact
  - **customer:** yo Xbox how come half of my friends can't get online and none of us can use party chat
- `2071187` · first contact
  - **customer:** is Xbox live server down? My WiFi is fine but Xbox won't connect.
- `713558` · first contact
  - **customer:** when will Xbox live be fix OK hopefully it fix soon
- `2301563` · first contact
  - _other_customer_: How are the #CoDWWII Servers for you currently? We've noticed long matchmaking times, unable to find lobbies and more! #CoDWW2 If you're still experiencing issues let us know your platform, region and type of problem. <…
  - **customer:** Xbox one, U.S., unable to connect to servers, party, disconnecting post match not counting towards contracts and orders, infinite load screens freezing the game/console
- `1706501` · follow-up
  - _customer_: hello anyone can tell me whats going onniver an hour now waiting to go online and play my game
  - _brand_: Hi there, what happens when you try to connect to Xbox Live on your Xbox 360 console? Please try these steps: <URL> to see if they can help out.
  - **customer:** Its on xbox 360 i can log in fine its when i go to play modern warfare 3 and connect to servers it keeps saying servers are down
- `1409571` · first contact
  - **customer:** Hello, I've been having a problem with Xbox Live on Xbox Live for 2 days - error 8015190 or 80151909B - Czech republic, Prague.

## 2. `install_download_update`

**Definition.** Getting software onto the console fails or stalls: game or app downloads and installs, disc installs, system updates, storage, or content that has to be re-downloaded.

**Include**
- 'Installation stopped', downloads stuck or slow, queue problems
- Console or game updates that fail, loop or error
- Games deleted or needing reinstall after an update; storage-full errors
- Disc games that won't install

**Exclude**
- Installed content that crashes or won't start → `software_game_app`
- Owned content the store won't let the customer get → `entitlements_subscriptions_codes`
- The disc drive not reading any disc → `hardware_devices`

**Response strategy.** Give install and update troubleshooting (clear local storage, offline system update, cancel and reinstall, check storage and the queue), or point to a known publisher-side issue.

**Default risk.** `low`. **Default escalation (draft).** Auto (ROUTINE_TROUBLESHOOTING). Escalate on REPEAT_CONTACT when an update has bricked the console and the steps have failed.

**Estimated training count.** ≈ 1,020 (95% range 590 – 1,720; 12 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `software_game_app` (3), `product_info_feedback` (1)

**Representative examples** (train; context shown where present):

- `903420` · first contact
  - **customer:** Guys I'm having major issues installing games on my Xbox One, Keep getting Installation stopped, but there's space on drive
- `805812` · first contact
  - **customer:** xbox one s wont update. It downloads and verifys then restarts and process starts over.
- `1236555` · first contact
  - **customer:** Fall updated deleted some of my games requiring a re-download and install again. (over 200GB) Some games are just missing. :(
- `2495936` · first contact
  - **customer:** my update keeps tapping and restarting. Error 0x8b5003c 0x0000000 0x00000206
- `1704319` · first contact
  - **customer:** Hey, I own a disc copy of a game that refuses to install, no updates, just the game, I've tried everything.
- `2304167` · first contact
  - **customer:** anytips to speed up downloads? ive been downloading 2k for almost two days now and its only at 40 percent.. :/
- `1093610` · follow-up
  - _customer_: Your update broke my Xbox and you expect me to pay to fix it. What kind of logic is that? 
  - _brand_: Hi there. Are you part of the Insider program by chance? Can you describe what the console is doing?
  - **customer:** no I'm not an insider member
- `960419` · first contact
  - **customer:** PLEASE HELP everytime i try to download fortnite on my xbox it downloads as an app and not as a game.. help asap

## 3. `hardware_devices`

**Definition.** A physical device misbehaves: console power, shutdowns, heat or noise, disc drive, display/HDMI, controllers, headsets, Kinect, external storage. Also repair, warranty and replacement. Controllers stay here; their subtype is internal.

**Include**
- Console won't power on, shuts down, has no signal, green dots, fan noise
- Disc drive won't read discs or scratches them; Blu-ray playback errors that point at the drive
- Controllers that won't pair, disconnect, desync, or have faulty buttons; headset and mic problems
- External drives not detected; device registration and warranty

**Exclude**
- One game or app freezing while everything else works → `software_game_app`
- Wrong item in the box, delivery or retailer problems → `purchases_billing_orders`

**Response strategy.** Give device troubleshooting (power cycle, another outlet, re-pair and update the controller, check the drive). If the device is faulty, route to the online repair or replacement process.

**Default risk.** `medium`. **Default escalation (draft).** Auto for first-line steps (ROUTINE_TROUBLESHOOTING). Escalate (ACCOUNT_SPECIFIC) when a repair, replacement or warranty decision is needed, or the steps have already failed.

**Estimated training count.** ≈ 1,620 (95% range 1,060 – 2,420; 19 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `software_game_app` (4), `purchases_billing_orders` (3)

**Internal subtypes** (never scored): `console`: Power, shutdowns, heat, noise, whole-console freezes; `disc_drive`: The disc drive, and reading discs or Blu-rays; `display_output`: HDMI, no signal, picture artefacts; `controller_accessory`: Controllers, headsets, Kinect, adapters; `external_storage`: External drives

**Representative examples** (train; context shown where present):

- `60195` · follow-up
  - _customer_: to Elizabeth from @user I don't know who you are but difficult to receive this kind of help 🙏💪🏽💪🏽🥇
  - _customer_: No to expensive, I lost a lot of things in the hurricane Maria
  - _brand_: We're very sorry to hear about that! If you have any other support questions, just let us know.
  - **customer:** I just try another power supply from my neighbor the Xbox turn on but in 5 seconds shut down by itself
- `1376956` · follow-up
  - _customer_: well I was enjoying #Madden18 on the daily but unfortunately today my Xbox died and I'll have to miss out 😥😥
  - _customer_: Yes 3 to be exact
  - _brand_: Thanks for that info. Is your console currently powering on, but displaying a blank screen?
  - **customer:** The tv displays no signal
- `2244439` · first contact
  - **customer:** My Project Scorpio isn't reading any discs....what do I need to do to get a replacement
- `2724934` · first contact
  - **customer:** not sure if it’s dodgy hdmi or gpu broke on Xbox one X intermittent green dots on the screen? :/ Only happening on dashboard? Like this? <URL>
- `2442246` · first contact
  - **customer:** my controller won't connect to my Xbox. It's battery powered. <URL>
- `1029282` · first contact
  - _brand_: Controller not working quite right? Make sure it's all up to date by following the steps here: <URL>
  - **customer:** All my controllers randomly disconnects. Be fine for a second then it doesn’t
- `2209929` · first contact
  - **customer:** Has anyone reported issues with the Xbox One X controller desyncing? My Project Scorpio edition keeps desyncing for no reason. @user
- `1371729` · first contact
  - **customer:** I bought a Seagate game drive for my Xbox 1 and its not showing
- `2202292` · first contact
  - **customer:** playing shadow of war on my new xb1x and occasionally the fan will ramp up very loudly for a couple of seconds. Is it normal?

## 4. `software_game_app`

**Definition.** Installed software misbehaves: a game or app crashes, won't launch or has a bug; dashboard/UI problems after an update; app features such as notifications, messaging, streaming and achievements. Merged for v1.

**Include**
- A specific game or app crashes, freezes, won't open, or shows an error code
- Dashboard/Guide UI broken or slow after an update; notifications, messages, keyboard
- Achievements not unlocking; in-game content or credits missing because of a bug
- Store or Xbox app crashing (the app itself, not a purchase)

**Exclude**
- Download or installation failures → `install_download_update`
- Can't reach Live or game servers → `connectivity_xbox_live`
- Paid content missing → `entitlements_subscriptions_codes`

**Response strategy.** Give app or game troubleshooting (power cycle, remove and re-add the profile, uninstall and reinstall, check whether the console is in the Insider preview). Point to the developer or publisher for game-side bugs and patches.

**Default risk.** `low`. **Default escalation (draft).** Auto (ROUTINE_TROUBLESHOOTING). Escalate on REPEAT_CONTACT when the steps have already failed; OUT_OF_SCOPE (developer) for patch timelines.

**Estimated training count.** ≈ 2,220 (95% range 1,550 – 3,090; 26 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `connectivity_xbox_live` (6), `hardware_devices` (4), `install_download_update` (3)

**Internal subtypes** (never scored): `game`: A specific game's bug, crash or content; `app`: A media or utility app, the Store app, messages, Mixer; `dashboard_system`: Dashboard, Guide, notifications, system UI

**Representative examples** (train; context shown where present):

- `966038` · first contact
  - **customer:** why is YouTube not working on Xbox one console???
- `1068162` · first contact
  - _customer_: been sitting here watching my game not start for over an hour. Little help here.
  - _other_customer_: Not gonnalie... think it is a @user @user issue not @user
  - **customer:** Can open any other game other than FIFA 18??
- `1548583` · follow-up
  - _customer_: fix the home screen on the Xbox one. I can’t even leave my party. The tabs are messed up. It won’t let me scroll past LFG
  - _brand_: Hi there! Let's try a full power cycle by following all the steps here: <URL> and check again.
  - **customer:** Didn’t help. It just made it worse. Can’t launch games, apps, and store. Not even spamming “A” works
- `1029276` · first contact
  - _brand_: Controller not working quite right? Make sure it's all up to date by following the steps here: <URL>
  - **customer:** I'm not receiving any notifications anymore and it's frustrating because I want tone talk to my friends
- `2624341` · first contact
  - **customer:** I uploaded a video using my Xbox One but didn't get the YouTube achievement or does it take a little while???
- `1848043` · first contact
  - _customer_: My Forza Horizon 3 screen freeze a lot. Why? Digital version
  - **customer:** Guys...? Please help
- `2302875` · first contact
  - **customer:** I nodded on a car on fm7 yesterday of 1.33million and today I came back to collect the credits and it won't let me help
- `1546338` · follow-up
  - _customer_: Why the fuck does the @user always crash? Like every damn time I go to use it. Trash. <URL>
  - _brand_: Greetings! Let's have you try resetting your router/modem and power cycling: <URL>
  - **customer:** Done that plenty of times, it’s definitely the store, I’ve seen others complain about the same issue.

## 5. `account_access_profile`

**Definition.** The customer's Microsoft/Xbox account itself: signing in with their credentials, recovery, creation, email/alias, gamertag, child/adult and family settings, profile data. A compromised account is this intent, with the SECURITY risk rule on top.

**Include**
- Can't sign in to *my* account, password or email recovery, account creation errors
- Gamertag changes and availability, email alias, tenure or profile data
- Child account rules and family settings
- Account hacked or used by someone else (the SECURITY rule applies)

**Exclude**
- Service-wide sign-in outages → `connectivity_xbox_live`
- Home Xbox and licences → `entitlements_subscriptions_codes`
- Another player's conduct → `enforcement_safety`

**Response strategy.** Link the self-service guide (recovery, alias, gamertag, family settings). Fixes that touch the customer's own account need identity verification, so hand off to chat or phone support.

**Default risk.** `medium`. **Default escalation (draft).** Escalate (ACCOUNT_SPECIFIC) when the fix needs the customer's own account, which is most cases. Auto (GENERAL_INFO) for general how-to questions such as child-account rules.

**Estimated training count.** ≈ 770 (95% range 410 – 1,410; 9 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `connectivity_xbox_live` (4), `entitlements_subscriptions_codes` (3)

**Representative examples** (train; context shown where present):

- `1678269` · first contact
  - **customer:** can’t sign in still or use any apps I even restarted my system and now can’t fully get my account back. It’s been 4 days now
- `1706513` · first contact
  - **customer:** I’m trying to make an account on Xbox and it keeps telling me that there is a problem?
- `345595` · follow-up
  - _customer_: my sons Xbox live account uses my wife’s email address. How can I change it to his own email address that I made for him?
  - _brand_: Hiya! To change the email that is associated with the account, let's have you follow the steps here: <URL>
  - **customer:** Will it cause my wife’s email account to be deleted? Asking as it wants me to create an alias and delete her address.
- `2018153` · first contact
  - **customer:** is there any way for a child account to stop being a child account ie promote it to an adult account?
- `1852555` · follow-up
  - _customer_: Need help with account and support hasn't helped so far! My tenure has been reduced by 2 years and I'm not sure why. Here's a status from November of 2015 showing me at 13 years. I've been on Live since beta testing in …
  - _customer_: Posted on the forums. And no, I've had no lapses. I'm about as active an Xbox user as there is. Been constant since 2002.
  - _brand_: Hmm, that may self-correct in the next few days and usually does. Let us know if you still see that changed by the end of the week. We will be here to look into it further.
  - **customer:** Thank you. It’s been that way for months but with the Fall update just rolling out officially, hopefully it’s fixed soon.
- `1061269` · first contact
  - **customer:** after 6 days, you guys determined indeed my account was hacked, why is it going to take another 3 days to give it back to me?
- `2258377` · first contact
  - **customer:** I gameshared with my friend and my 5 home consoles got used up so I got them reset and didn’t gameshare and my account was hacked and I’m not home anymore and they already used 5 whoever hacked my account. I need help getting 1 switch for my consle. I have my acc now
- `2232817` · first contact
  - **customer:** Legit question here, Do you know when you re rolling gamertags again? Or any idea when? I been in longing for a gamertag that has Zero g.s. for years now and the account is dead

## 6. `purchases_billing_orders`

**Definition.** The money or the order: purchases that fail, unexpected or duplicate charges, refunds, pricing and sales, pre-order deliveries, wrong items, retailer problems. Kept separate from entitlements.

**Include**
- Purchase fails with a payment error; payment method problems
- Charged twice or unexpectedly; refund requests; sale price not honoured
- Pre-order delivery or shipment; wrong item in the box; retailer issues

**Exclude**
- Paid, but the game, membership or code isn't showing → `entitlements_subscriptions_codes` (T5)
- Policy questions with no problem ('why does a free game need a card?') → `product_info_feedback`

**Response strategy.** Acknowledge, share generic tips if relevant (check the payment info, try the web store), then route charges, refunds and orders to billing/chat support, and retailer orders to the retailer.

**Default risk.** `high`. **Default escalation (draft).** Always escalate (BILLING_DISPUTE for charges and refunds, otherwise ACCOUNT_SPECIFIC). Generic tips may go in the reply, but a person owns the case.

**Estimated training count.** ≈ 600 (95% range 290 – 1,190; 7 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `entitlements_subscriptions_codes` (5), `hardware_devices` (3)

**Representative examples** (train; context shown where present):

- `917784` · first contact
  - **customer:** This is what it says when I'm trying to buy the Friday the 13th 8 movie collection. HELP <URL>
- `941532` · first contact
  - **customer:** I'm having an issue with buying the Friday the 13th 8-Movie collection. Getting HRESULT: 0xc33507d1 CV: y1SY3VcE/kiJaJxH.48
- `23503` · first contact
  - _brand_: Have an Xbox support question & haven't heard back from us yet? Send another tweet our way if you need help!
  - **customer:** I’ve been charged twice for Star Wars battlefront 2
- `2289318` · first contact
  - **customer:** how do I refund a game my sibling brought while I was out of the country ?
- `2244688` · follow-up
  - _customer_: I’ve been charged over 7 times at once for my game pass subscription and now you’re saying you can’t give a refund right now? I need an explanation
  - _brand_: Hey, who told you that you can not have a refund?
  - **customer:** I was told that even though they can see the error, my money couldn’t be refunded at this time and they couldn’t give me a time when it couldn’t. I have bills to pay
- `15148` · follow-up
  - _customer_: hey I've got a question about the Xbox One X Scorpio edition.
  - _brand_: Hello, thanks for reaching out to us. What seems to be the issue?
  - **customer:** I pre ordered The Scorpio edition the day of the announcement on Amazon and I'm worried that it won't come on release date. It still tells me the date is pending. Amazon told me they are waiting to hear from Microsoft.
- `1765600` · first contact
  - _other_customer_: This is why I love this industry. #XboxOneX #FeelTruePower <URL>
  - **customer:** Hey, my Scorpio has arrived but has the wrong pad. I’ve got the One X controller not the Scorpio... @user and @user aren’t responding. <URL>
- `2129547` · first contact
  - **customer:** 45 pages of FAILED RELEASE DATE DELIVERIES.... but still not a peep from @user @user as to where these orders are... @user has denied any delays with shipments. So what is the reason for the delays? <URL>

## 7. `entitlements_subscriptions_codes`

**Definition.** Something the customer is entitled to isn't recognised or delivered: Gold / Game Pass memberships and trials, code or gift-card redemption, DLC and pre-order bonuses, owned games missing, licences, Home Xbox, game sharing. Merged for v1.

**Include**
- Gold or Game Pass bought or active but not recognised; trial questions
- Codes or gift cards that won't redeem; beta or early-access codes
- Pre-order bonuses, DLC or season-pass items, or purchased games missing from the library
- Home Xbox changes, game sharing, licences for owned games

**Exclude**
- Payment failures, double charges, refunds → `purchases_billing_orders`
- Bare error codes unrelated to redemption → `software_game_app` / `connectivity_xbox_live`

**Response strategy.** Give entitlement troubleshooting (check subscriptions and order history, remove and re-add the profile, power cycle, follow the redemption guide). Hand off if it's still missing.

**Default risk.** `medium`. **Default escalation (draft).** Auto for first-line steps (ROUTINE_TROUBLESHOOTING). Escalate (ACCOUNT_SPECIFIC) when a specific code, charge or licence has to be looked up, or the steps have failed.

**Estimated training count.** ≈ 1,190 (95% range 720 – 1,930; 14 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `purchases_billing_orders` (5), `account_access_profile` (3), `connectivity_xbox_live` (0)

**Internal subtypes** (never scored): `membership`: Gold / Game Pass / trials / free-play promotions; `code_redemption`: Codes, gift cards, keys; `dlc_bonus_content`: DLC, pre-order bonuses, season-pass items; `purchased_item_missing`: Paid for, but the item isn't in the library; `licence_home_sharing`: Licences, Home Xbox, game sharing

**Representative examples** (train; context shown where present):

- `1649377` · first contact
  - **customer:** Preordered COD WW2 and I️ have the preorder bonuses installed but haven’t received them in game plz help
- `2300747` · first contact
  - **customer:** can u help me please i bought a 12 month abonnement and i cant play in live because it tells me i need to buy an abonnement i dont understand... <URL>
- `1410288` · first contact
  - **customer:** My redeem a code doesn't work, it keeps telling me to wait a bit but I've waited all day and still says the same thing
- `1758424` · first contact
  - **customer:** I‘ e bought an xbox live gold key for 14 days and I redeemed it 1 hour ago, but when I want to play online it says that..(1/2) my account doesn’t have the authorization to play online..I‘ve started my xbox one new (5 times) and it shows the same..(2/2)
- `1550471` · first contact
  - **customer:** your marketplace is terrible,you charged me for a game and its not even in my ready to install. Its gone!
- `1777618` · first contact
  - **customer:** I need help with "My Home Xbox" it bugged out and wouldn't let my games change over so i tried it again and it said i have reached my Max amount of Times this year but I've only done it twice Can Someone please help?
- `2365309` · first contact
  - **customer:** my brother preordered starwars battlefront 2 the deluxe edition and I’m game sharing with him can I play it early to then? Because it’s doesn’t say I got the deluxe version
- `2108979` · first contact
  - **customer:** Hey @user Why don't the GamePass codes that ship in consoles work? I have two get the same error with both.

## 8. `enforcement_safety`

**Definition.** Suspensions, bans and enforcement messages; reports of other players' conduct (harassment, threats, cheating); code-of-conduct questions; content rejected by moderation.

**Include**
- 'Why was I banned or suspended?', appeals, enforcement notices
- Reporting another player, harassment, 'why wasn't action taken?'
- Rejected gamerpics or content; code-of-conduct questions

**Exclude**
- The customer's own account being hacked → `account_access_profile`
- Anger at support with no enforcement topic → `support_process_complaint`

**Response strategy.** Use the fixed policy reply: support can't discuss or influence enforcement; point to the enforcement site and case review, and explain how to report players. Never speculate about an outcome.

**Default risk.** `medium`. **Default escalation (draft).** Auto with the policy template (GENERAL_INFO). The SAFETY_LEGAL rule escalates threats of harm, minors at risk and doxxing.

**Estimated training count.** ≈ 510 (95% range 240 – 1,080; 6 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `support_process_complaint` (1)

**Representative examples** (train; context shown where present):

- `1298728` · first contact
  - **customer:** kinda fed up of Xbox as a company now they have banned me for the 4th time now stupid and each time is 2 week bans
- `891188` · first contact
  - _brand_: Have Call of Duty: WWII pre-ordered? Make sure your payment info is accurate here: <URL>
  - **customer:** Xbox my brother sent a message calling someone a tryhard and we got this message. Is this a warning or does it give us a punishment. <URL>
- `1531834` · first contact
  - **customer:** why am I not aloud to have any custom gamer pics all I had a was an image of Dva from @user it wasn’t even sexual wtf 😪
- `2244476` · first contact
  - **customer:** this is not true you've banned me Harassment but i did not harass anybody and i have proof <URL>
- `431515` · first contact
  - **customer:** user "sabbath buried" has been harassing me for months now can you please take action? @user @user <URL>
- `2181311` · follow-up
  - _customer_: can i get some support
  - _brand_: Hi, how can we assist you?
  - **customer:** i have been banned for threats of harm 3 days after i was communication banned and i dont know how i could threaten to harm someone when i was already banned from messaging or talking to people?
- `2188986` · first contact
  - _brand_: Hi there, rest assured our enforcement team takes all reports seriously. If this
  - **customer:** Why hasnt anything happened then?
- `344739` · follow-up
  - _customer_: Please help me, there is a person who kept spam reporting me and I got suspended <URL> I already gave a case review, but I question I have is why is my brothers account suspended when only me account got spammed?
  - _customer_: The account is perfect and it has never got any enforcements. Case reviews take a while to get a response so can you do anything? (2/2)
  - _brand_: That's usually a sign of a console ban. our phone team would have more info: <URL>
  - **customer:** Also are you saying that I might be banned for getting spammed? If so, that's really unfair.

## 9. `product_info_feedback`

**Definition.** Questions about how things work or what's available, and feedback or feature requests: specs, compatibility, backward compatibility, setup, how-tos, availability, policies, suggestions, negative opinions on design or updates. Questions and feedback stay merged.

**Include**
- How-to and 'does X support Y' questions (1080p streaming, external SSD, setup without internet)
- Backward-compatibility and content availability requests
- Feature requests and negative opinions on design or updates
- Policy questions (why a payment method is needed, trial limits in general)

**Exclude**
- The customer reports that something is failing → the matching issue intent (T10)
- Praise with no request → `social_offtopic` state (S2)

**Response strategy.** Answer the factual question from the knowledge base. For suggestions, thank the customer and point to the feedback site. Never speculate on release dates or the roadmap.

**Default risk.** `low`. **Default escalation (draft).** Auto (GENERAL_INFO). OUT_OF_SCOPE when the answer belongs to a third party (a publisher or retailer).

**Estimated training count.** ≈ 1,280 (95% range 790 – 2,030; 15 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `install_download_update` (1)

**Representative examples** (train; context shown where present):

- `1595815` · first contact
  - **customer:** The Xbox One X has faster load times from the internal HDD. Will I still benefit from using an external SSD?
- `1376297` · first contact
  - _other_customer_: been saying they should do this for years.. also this just exposed the kellyanne conway of the youtube world for "alternative facts" ;) <URL>
  - _customer_: Works for Destiny. And in 2017 how many people really don't have internet if they own a 4th gen console? Even for updates if not playing OL
  - _other_customer_: Best Destiny is a persistent online game. CoD SP doesn't require an active internet connection. I do agree it shouldn't effect most though.
  - **customer:** Doesn't XBOne require an internet connection to set up or update? Or have I mis-remembered again?
- `1769680` · first contact
  - **customer:** How can I stream in 1080p on Mixer on Xbox One, I have the 2017 Xbox Fall Update
- `2382110` · first contact
  - **customer:** I just became a gold member, now how do I downloaded a 360 game that's free without putting in my credit card? Why would I have to give my credit card if the game is free. What if a kid wanted to download these games and they don't have a credit card?
- `1371151` · first contact
  - **customer:** I would love to put the backward compatibility of alien vs. predator
- `870619` · first contact
  - **customer:** Love having app on XBO. Will the ability to listen as a party be added soon?That might just perfect it.
- `2232755` · first contact
  - **customer:** instead of mixer. can you add youtube streaming??? PLEASE
- `1141440` · first contact
  - **customer:** Wtf is this new update Xbox!!!!! It is actual aids @user @user

## 10. `support_process_complaint`

**Definition.** The message is mainly about the support experience, not a product problem: unanswered or repeated contacts, rude or unhelpful agents, demands for a human or another channel, general 'no one helps'.

**Include**
- 'Still waiting for help', 'chatted 4 times, still no solution'
- Complaints about an agent or phone support; 'are you going to help me or not?'
- Asks for another channel because the offered one doesn't work for them

**Exclude**
- A complaint that names a concrete product issue → that issue's intent, with the REPEAT_CONTACT / HIGH_ANGER risk rules
- Anger about bans → `enforcement_safety` (T8)
- Vague help requests without a complaint about support → `needs_more_context` (T9)

**Response strategy.** Apologise, acknowledge the history, ask for the one missing detail or offer the right channel, and hand the case to a person.

**Default risk.** `high`. **Default escalation (draft).** Always escalate (REPEAT_CONTACT, or HIGH_ANGER when no repeat contact is stated).

**Estimated training count.** ≈ 510 (95% range 240 – 1,080; 6 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `needs_more_context` (4), `enforcement_safety` (1)

**Representative examples** (train; context shown where present):

- `414172` · first contact
  - **customer:** Chatted in 4 times still no solution @user @user @user And no answer on my forum post! <URL>
- `1370514` · first contact
  - **customer:** just because he can’t understand what I tell him doesn’t mean he can be an ass
- `1451336` · follow-up
  - _customer_: Furious @user phone support,very rude hanging up the phone several times. Not customer service you would expect or except.
  - _brand_: Apologies for any frustrations, if you wish, we could help troubleshoot with you!
  - **customer:** Us a customer/consumer have rights
- `365015` · follow-up
  - _customer_: my game wont load when i put it in the xbox?? the disc isnt scratched or anything?
  - _customer_: <URL>
  - _brand_: Alright, let's try with a fresh start by unplugging the console and your router/modem for a full 5 minutes then check again. Also when you plug the console back in make sure it's plugged into a wall socket.
  - **customer:** yall gonna help me or not?
- `1534637` · first contact
  - **customer:** Still waiting to receive help with my issue
- `1029357` · first contact
  - **customer:** Ive had the same problem for almost 2 weeks and ive talked to NUMEROUS support "Specialists" No one knows whats wrong. No one can provide me with a solution either
- `2370318` · first contact
  - **customer:** 🕛🕧🕐🕜🕑🕝🕒🕞🕓🕟🕟🕔🕔🕠🕘🕣🕗🕢🕡🕕🕤🕙🕥🕚🕦🕦☀️🌒 & still waiting for help
- `248431` · follow-up
  - _customer_: #huracainemaria #noelectricity #nointernet #pue… <URL> <URL>
  - _brand_: Oh no. For something like this let's reach out to our chat team here: <URL> . They could go over your options.
  - **customer:** I can barely stay connected to the internet, comunications, water and electricity are down. Thats why I ask here, I can't chat right now. 😣

## 11. `needs_more_context`

**Definition.** Even with the available thread context, the support issue can't be determined confidently enough to act.

**Include**
- A bare help request, image or link only: 'Any ideas or help? <URL>', 'Hello? Need assistance'
- 'Having the same issues too' with no thread to inherit from
- A pointer to an earlier question that isn't in the data; frustration with a screenshot only

**Exclude**
- Follow-ups whose issue is in the context → the thread's intent (`issue_followup`)
- Complaints about support itself → `support_process_complaint` (T9)

**Response strategy.** Ask exactly one targeted clarifying question that names the missing detail (e.g. 'Which console, and what exact error text do you see?'). Never send a generic reply or a guess.

**Default risk.** `low`. **Default escalation (draft).** Auto: the clarification is sent (GENERAL_INFO). Escalate (LOW_CONFIDENCE) if the brand has already asked for clarification in this thread (DRAFT; to be calibrated on dev).

**Estimated training count.** ≈ 600 (95% range 290 – 1,190; 7 of 150 in the discovery sample).

**Top confusable intents** (pairs seen in coding): `support_process_complaint` (4)

**Representative examples** (train; context shown where present):

- `743704` · first contact
  - **customer:** Any ideas or help? <URL>
- `899017` · first contact
  - **customer:** Hello? Need assistance ffs
- `2264062` · first contact
  - **customer:** having the same issues too I reset and delete and reinstall <URL>
- `2453133` · first contact
  - **customer:** care to lend any assistance on the question below? Had some help via other user but interested in your take <URL>
- `2055978` · first contact
  - **customer:** What's wrong with my Xbox! It's doing the stupidest crap ever! @user @user I NEED THE XBOX ONE X!!! I CAN'T STAND THIS!
- `2438004` · first contact
  - **customer:** I fucking hate these messages!! Please Fuuuuucking help me!!!!!! Peace of shits!! <URL>
- `205579` · first contact
  - **customer:** help with starwars beta please

## Deterministic tie-break rules

Apply in this order: S1–S2 decide the state, T0 picks the primary intent of a multi-issue message, T1–T11 settle between two intents, and T12 comes last. `seen` = how often the pair appeared as (chosen, runner-up) in the discovery sample.

- **S1**: `acknowledgement_closing` vs `issue_followup`. Label `acknowledgement_closing` only if **no unresolved support issue remains**: the customer confirms a fix, or thanks or says okay with nothing open. If the problem persists, new details are given, anything is asked, or the customer will try something or report back later ('will try tonight', 'I'll get back to you'), label `issue_followup` with the thread's intent. See the S1 examples table. _Examples: `1523187`, `866890`._
- **S2**: `social_offtopic` vs `product_info_feedback`. If the message contains a suggestion, a request, a question, or a negative opinion on design, label state `new_issue` with intent `product_info_feedback`. Otherwise (praise, banter, promotion) label `social_offtopic`. _Examples: `2006809`, `1141440`._
- **T0**: any two intents. If a message raises two or more issues, the **primary** (scored) intent is the one with the higher default risk (high > medium > low). If they are tied, it's the one mentioned first. The others go in `secondary_intents`, which is internal and never scored. _Examples: `2114221`, `1540213`._
- **T1**: `software_game_app` vs `hardware_devices` (seen 4). If the symptom affects the whole console or a device (power, no signal, shutdown, disc drive, noise, pairing, a broken controller), label `hardware_devices`. Otherwise (one game, app or screen), label `software_game_app`. _Examples: `1118847`, `1548583`._
- **T2**: `software_game_app` vs `install_download_update` (seen 3). If it fails while being downloaded, installed or updated (progress, queue, storage, update error), label `install_download_update`. If it is installed but misbehaves when run, label `software_game_app`. _Examples: `903420`, `1068162`._
- **T3**: `connectivity_xbox_live` vs `software_game_app` (seen 6). If the customer can't reach Xbox Live, a game's servers or a party, or is disconnected or lagging, label `connectivity_xbox_live`. If a feature is broken while online works, label `software_game_app`. _Examples: `2301563`, `966038`._
- **T4**: `connectivity_xbox_live` vs `account_access_profile` (seen 4). If sign-in fails because of this customer's credentials, recovery, creation or profile, label `account_access_profile`. If sign-in fails for many users, or because of the network or an outage, label `connectivity_xbox_live`. _Examples: `1678269`, `713558`._
- **T5**: `entitlements_subscriptions_codes` vs `purchases_billing_orders` (seen 5). If the money moved and the item, membership or code is missing or unrecognised, label `entitlements_subscriptions_codes`. If the problem is the transaction itself (it fails, is duplicated, needs refunding, or the order hasn't arrived), label `purchases_billing_orders`. _Examples: `1550471`, `23503`._
- **T6**: `entitlements_subscriptions_codes` vs `connectivity_xbox_live` (seen 0). If 'can't play online' comes with a mention of Gold, Game Pass, a trial, a code, or 'profile not allowed to play Xbox Live', label `entitlements_subscriptions_codes`. Otherwise label `connectivity_xbox_live`. _Examples: `1758424`, `2071187`._
- **T7**: `entitlements_subscriptions_codes` vs `account_access_profile` (seen 3). If it's about what the customer may use (licences, Home Xbox, game sharing, memberships), label `entitlements_subscriptions_codes`. If it's about who the customer is (sign-in, identity, age, gamertag, profile), label `account_access_profile`. _Examples: `1777618`, `2018153`._
- **T8**: `enforcement_safety` vs `support_process_complaint` (seen 1). If the message mentions a ban, suspension, report, moderation or the enforcement team, label `enforcement_safety`. Otherwise label `support_process_complaint`. _Examples: `2415198`, `1370514`._
- **T9**: `support_process_complaint` vs `needs_more_context` (seen 4). If the message complains about support responsiveness or quality (waiting, unanswered, rude, 'no one helps'), label `support_process_complaint`. If it's only a vague request for help, label `needs_more_context`. _Examples: `1534637`, `899017`._
- **T10**: `product_info_feedback` vs `install_download_update` (seen 1). If the customer reports that something failed ('can't install X'), label the matching issue intent (here `install_download_update`); the reply grounds any product fact, such as backward-compatibility status. If the customer asks whether or how something exists or works, label `product_info_feedback`. _Examples: `1697828`, `1595815`._
- **T11**: `hardware_devices` vs `purchases_billing_orders` (seen 3). If the device itself is faulty (including a warranty claim for a fault), label `hardware_devices`. If the problem is delivery, a wrong item, or a retailer dispute, label `purchases_billing_orders`. _Examples: `2244439`, `1765600`._
- **T12**: `needs_more_context`. Use `needs_more_context` only if, after reading the message and the thread context, no intent definition and no rule above applies with confidence. Never use it for a follow-up whose thread states the issue. _Examples: `743704`, `1848043`._

## Risk and escalation (a layer on top of intent)

_Escalation policy status: **DRAFT**._

| level | meaning |
|---|---|
| `low` | Safe to auto-handle with public guidance. |
| `medium` | Auto-handle the first-line answer, but watch for the conditions in the intent's escalation policy. |
| `high` | Involves money, identity, safety or an already-failed support experience. Always escalate. |

| rule | fires when | Phase 2 signal (weak cue) | raises risk to | reason code |
|---|---|---|---|---|
| `account_compromised` | Someone else is using or has taken the account; hacked; unauthorised sign-ins or purchases. | `security` | `high` | `SECURITY` |
| `harm_or_legal` | Threats of violence or self-harm, minors at risk, doxxing; lawsuits, police, lawyers, regulators. | `legal_threat` | `high` | `SAFETY_LEGAL` |
| `money_dispute` | Charged twice or without consent, refund refused, money taken. | `billing_dispute` | `high` | `BILLING_DISPUTE` |
| `repeat_contact` | Says they already contacted support, already did the steps, or have waited days; or has earlier threads. | `repeat_contact_cue`, `prior_contact` | `medium` | `REPEAT_CONTACT` |
| `strong_anger` | Profanity or abuse aimed at the brand, threats to leave. | `anger` | `medium` | `HIGH_ANGER` |

- **DRAFT, not frozen.** These thresholds are calibrated on the 40-item dev set (see the calibration plan) before golden labelling.
- `risk_level` = the highest of the primary intent's default risk (`low` for states without an intent) and the risk of every rule that fires.
- `escalate = yes` if any of these hold: `risk_level` is high; the intent's escalation policy calls for it (e.g. purchases always, account when account-specific, hardware when a repair is needed); `repeat_contact` fires and the customer says the steps already failed; `strong_anger` fires on an intent whose default risk is medium or high; it's `needs_more_context` and the brand has already asked for clarification.
- `reason_code`, when escalating, is the first match in this order: SECURITY > SAFETY_LEGAL > BILLING_DISPUTE > ACCOUNT_SPECIFIC > REPEAT_CONTACT > HIGH_ANGER > OUT_OF_SCOPE > LOW_CONFIDENCE. When not escalating: ROUTINE_TROUBLESHOOTING for fixes, GENERAL_INFO otherwise.
- These rules apply on top of any intent or state. There are no intents for hacked accounts, anger or threats.
- Phase 2's `customer_escalation_signals` (keyword cues) map onto these rules as shown in the signal column. They are weak hints only; the labeller decides.

## Escalation calibration plan (dev set)

**Status:** the escalation policy stays DRAFT until this calibration is done. Then it is frozen and recorded in `DECISIONS.md`.
**Dev set:** 40 holdout exchanges, one per thread, all eval-eligible: 16 random and 24 targeted (4 per behaviour below). Drawn by `scripts/sample_dev.py` into `data/golden/dev_labeling_sheet.csv`. The sheet is blind: which slice each item came from is kept in `dev_sample_key.csv`. Dev is used for tuning only. It is never reported, never used for few-shot examples, and never put in the index.
**Labelling:** a human labels dev with this codebook: state, intent, secondary intents, risk, escalate, reason, label confidence. The cue columns are yes/no. No model pre-fill, to avoid anchoring.
**Procedure:** apply the draft combination rules to the labelled intents and cues, and compare the result with the labeller's own `escalate` decision on each item. Change a rule only where the dev evidence disagrees, then record the change and freeze.
**Behaviours to calibrate:**
- `strong_anger`: should anger alone escalate a low-risk intent, or only medium/high ones (the current draft)?
- `repeat_contact`: escalate on any repeat contact, or only when the customer says the steps already failed (the current draft)?
- Account-specific handling: which `account_access_profile` requests stay auto (how-to), and which need the customer's own account (escalate)?
- Low-confidence escalation: a threshold on the classifier's confidence. This is set on dev once the classifier exists (Phase 7). Until then, `label_confidence` flags items that are ambiguous even for humans.
- `needs_more_context` after a prior clarification: escalate the second vague message, or ask once more?
- Repair / replacement: escalate as soon as a repair is mentioned, or only after first-line steps fail (the current draft)?
**Then:** sample and label the 200-item golden set from the holdout, excluding every dev thread. This happens only once both the taxonomy and the escalation policy are frozen.

## How the golden set will be scored

How the golden set will be scored (`src/eval`, Phase 9). Every metric gets a bootstrap 95% CI and is reported separately for the random and stratified slices.
- **Conversation state:** accuracy and macro-F1 over the 4 states, on all items.
- **Intent:** macro-F1 over the 11 intents, **conditional on intent-bearing states**: only items whose gold state is `new_issue` or `issue_followup`. A missing or extra intent prediction counts as an error. Also reported: per-intent precision, recall and F1, and the confusion matrix.
- **Escalation:** precision and recall of `escalate = yes` on all items. **Must-escalate recall** is the recall on items whose gold `risk_level` is high or whose gold reason is SECURITY, SAFETY_LEGAL or BILLING_DISPUTE. This is the safety metric.
- **Joint routing correctness:** the share of items where the state is right, the primary intent is right (when the gold state carries one), and `escalate` is right, all at once.
- **Never scored:** `secondary_intents`, `subtype`, `event_tag`. `reason_code` agreement is reported for information only.
- **Analysis slices:** first contact vs follow-up, and event-tied vs not, where event tags were noted.

## Internal fields: secondary intents, subtypes, events

_Internal notes for analysis only. `secondary_intents`, subtypes and event tags are **not** benchmark labels and are never scored._

**Secondary intents in the discovery sample** (multi-issue messages; T0 picked the primary)

- `1540213`: primary `software_game_app`, secondary `connectivity_xbox_live`
- `2114221`: primary `hardware_devices`, secondary `connectivity_xbox_live`
- `2157949`: primary `connectivity_xbox_live`, secondary `software_game_app`
- `2301563`: primary `connectivity_xbox_live`, secondary `software_game_app`

4 of 133 intent-bearing exchanges raised more than one issue.

**Subtypes in the discovery sample**

- `hardware_devices` (19 coded): `console` 3, `disc_drive` 5, `display_output` 2, `controller_accessory` 8, `external_storage` 1; untagged 0
- `software_game_app` (26 coded): `game` 9, `app` 10, `dashboard_system` 7; untagged 0
- `entitlements_subscriptions_codes` (14 coded): `membership` 4, `code_redemption` 1, `dlc_bonus_content` 1, `purchased_item_missing` 2, `licence_home_sharing` 5; untagged 1

**Event tags** (train-period events; a temporal-generalization risk because the holdout covers 15 Nov – 3 Dec 2017)

| event | definition | coded rows | intents / states |
|---|---|---|---|
| `fall_update_2017` | The Xbox One Fall Update (Oct 2017): dashboard redesign, update problems, praise and complaints | 12 | software_game_app 3, acknowledgement_closing 2, install_download_update 2, social_offtopic 2, product_info_feedback 2, connectivity_xbox_live 1 |
| `cod_wwii_launch` | Call of Duty: WWII launch (Nov 3, 2017): server and pre-order issues | 4 | entitlements_subscriptions_codes 2, support_process_complaint 1, connectivity_xbox_live 1 |
| `battlefront2_launch_beta` | Star Wars Battlefront II beta and launch (Oct–Nov 2017) | 5 | entitlements_subscriptions_codes 3, needs_more_context 1, install_download_update 1 |
| `xbox_one_x_launch` | Xbox One X / Project Scorpio launch (Nov 7, 2017): deliveries, new-console issues | 11 | hardware_devices 4, purchases_billing_orders 3, product_info_feedback 2, acknowledgement_closing 2 |
| `xbox_live_outage` | Xbox Live sign-in or service outages acknowledged by the brand | 5 | connectivity_xbox_live 3, acknowledgement_closing 1, install_download_update 1 |
| `friday13_movie_sale` | Friday the 13th movie-collection sale whose purchase failed | 3 | purchases_billing_orders 2, account_access_profile 1 |
| `hurricane_maria` | Customers affected by Hurricane Maria (Puerto Rico, 2017) | 2 | support_process_complaint 1, hardware_devices 1 |

Share of each intent's coded rows that are tied to a train-period event:

- `connectivity_xbox_live`: 5 of 12
- `install_download_update`: 4 of 12
- `hardware_devices`: 5 of 19
- `software_game_app`: 3 of 26
- `account_access_profile`: 1 of 9
- `purchases_billing_orders`: 5 of 7
- `entitlements_subscriptions_codes`: 5 of 14
- `enforcement_safety`: 0 of 6
- `product_info_feedback`: 4 of 15
- `support_process_complaint`: 2 of 6
- `needs_more_context`: 1 of 7

## Exploratory topic evidence

Exploratory NMF topics over the 9,574 train first contacts (`results/taxonomy/topics.md`), mapped onto v1:

| topic (top terms) | share | maps to |
|---|---|---|
| 13: controller, console, elite, turn, connect, button | 14.0% | `hardware_devices` (mixed with generic console symptoms) |
| 14: store, app, try, buy, bought, messages, purchase | 9.0% | mixed: `purchases_billing_orders`, `entitlements_…`, `software_game_app` |
| 3: update, dashboard, fall update, notifications | 8.0% | `install_download_update` + dashboard subtype of `software_game_app` (event `fall_update_2017`) |
| 1: url, stuck, screen, message | 7.7% | screenshot-only: `needs_more_context`, some `enforcement_safety` notices |
| 0: user, shit, xboxonex, great | 7.7% | venting and tagging: `social_offtopic` state, `support_process_complaint` |
| 9: games, download, install, disc, load | 7.4% | `install_download_update`, disc part of `hardware_devices` |
| 12: play online, gold, friends | 6.5% | `connectivity_xbox_live` + membership subtype of `entitlements_…` |
| 11: pre-order, edition, scorpio, battlefront, beta | 6.2% | `entitlements_…` + `purchases_…` (launch events) |
| 5: account, sign, email, password, banned | 6.0% | `account_access_profile` (+ some `enforcement_safety`) |
| 2: game, bought, refund, game pass | 5.4% | `purchases_…` + `entitlements_…` |
| 4: code, error code, redeem | 4.5% | split by meaning: redeem → `entitlements_…`, error code → issue intents |
| 10: having trouble, internet, signing, party | 4.4% | `connectivity_xbox_live` |
| 7: party, chat, friends, hear | 4.4% | `connectivity_xbox_live` (party UI → `software_game_app`) |
| 6: live, connect, gold, subscription, service | 3.7% | `connectivity_xbox_live` + `entitlements_…` |
| 8: servers, cod, wwii | 3.1% | `connectivity_xbox_live` (event `cod_wwii_launch`) |

What the topics can't show:
- No topic isolates `enforcement_safety`, `support_process_complaint` or `needs_more_context`. These are defined by the strategy they need, not by vocabulary.
- Topics cover first contacts only, so they miss the follow-ups and closings that conversation state captures.

## Remaining risks

- **Rare intents:** enforcement, support complaints, purchases and needs_more_context are each ~4–5%. The stratified golden slice should top each up to about 10.
- **Temporal generalization:** see the event-tied share per intent in the internal fields section. Report golden results split by event-tied vs not.
- **Language filter leak:** one sampled message was German, so expect a few more.
