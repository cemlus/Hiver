# Codebook (v1, 2026-09-11)

> **Taxonomy FROZEN (v1, 2026-09-11): 11 intents and 4 conversation states. Escalation policy FROZEN (2026-09-11) after calibration on the 40-item dev set. The 200-item golden set is labelled against this version.** Generated from `data/taxonomy/taxonomy_v1.yaml` by `scripts/taxonomy_explore.py render`; edit the YAML, not this file. The evidence behind it is in `results/taxonomy/proposal.md`.

> **Evidence status.** The 150 exchanges in `data/taxonomy/discovery_sample_coding.csv` are **taxonomy discovery evidence, not the evaluation gold set.** One person (the assistant, while drafting) coded them to find and size candidate intents. They come from the **train** split, so they can never enter dev or golden. The golden set will be sampled from the holdout split and labelled against the frozen codebook. Counts derived from this sample are rough estimates.

## Label fields

| field | when | values |
|---|---|---|
| `conversation_state` | always, scored | One of the 4 states below. |
| `intent` | scored, only when the state is `new_issue` or `issue_followup` | Exactly one of the 11 intents below: the **primary** intent, chosen by T0 when a message raises several issues. Blank for `acknowledgement_closing` and `social_offtopic`. |
| `secondary_intents` | optional, internal, never scored | The other intent(s) of a multi-issue message, separated by `;`. Each must have a default risk no higher than the primary's (that's what T0 guarantees). |
| `risk_level` | always | `low` / `medium` / `high`. Start from the primary intent's default risk (`low` for states without an intent), then apply the risk rules; the highest wins. |
| `escalate` | always, scored | `yes` / `no`, from the escalation rules. It is decided separately from the intent. |
| `reason_code` | always | Escalation: SECURITY, SAFETY_LEGAL, BILLING_DISPUTE, ACCOUNT_SPECIFIC, REPEAT_CONTACT, STEPS_FAILED, HIGH_ANGER, OUT_OF_SCOPE, LOW_CONFIDENCE. Auto: ROUTINE_TROUBLESHOOTING, GENERAL_INFO. REPLY_FAILED_CHECKS is set only by the agent when its own drafted reply fails validation; labellers never use it. |
| `subtype, event_tag` | optional, internal, never scored | Analysis notes only. |

## Procedure

1. Read the context turns, oldest first, then the customer message. Ignore the historical brand reply: the classifier won't see it.
2. Choose `conversation_state`. Apply S1 and S2 when unsure. `acknowledgement_closing` needs **no unresolved issue left**.
3. If the state carries an intent, choose one primary intent from the definitions. If several issues are raised, T0 picks the primary and the rest go in `secondary_intents`. If two intents fit one issue, apply T1–T11 in order. Use `needs_more_context` only through T12.
4. Set `risk_level`: start from the primary intent's default risk, apply every risk rule that fires, and keep the highest.
5. Set `escalate` and `reason_code` from the escalation combination rules.
6. Optionally note `subtype` and `event_tag`.

## Conversation states

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

## Intents

### `connectivity_xbox_live`

The customer can't reach Xbox Live or a game's online service, or their online session is unstable: service sign-in, disconnects, lag, NAT, party chat connection, game servers, or 'is Live down?'.

- **Include:** Xbox Live or game servers down, unreachable or 'failed to allocate'; outage and status questions; Disconnects, lag, NAT type, lobby or matchmaking failures; Party chat that won't connect, drops people, or has no audio because of connection or privacy settings; Network errors during setup (can't get online)
- **Exclude:** Credential problems (forgotten password, recovery, account creation) → `account_access_profile`; 'Can't play online, it says I need Gold' → `entitlements_subscriptions_codes`; An app or game misbehaving while online works, and party menu/UI glitches → `software_game_app`
- **Response strategy:** Check for a known outage first and point to the status page. Otherwise give network troubleshooting: power cycle the console and router, check NAT and detailed network stats, wired vs Wi-Fi.
- **Default risk:** `low`. **Default escalation:** Auto (ROUTINE_TROUBLESHOOTING, or GENERAL_INFO for outages). Escalate (STEPS_FAILED) when the standard steps have already failed.
- **Examples:**
- `332201` · first contact
  - **customer:** error 0x800c0005 when joining any party I have open nat wired connection and fully rebooted everything
- `2196917` · first contact
  - **customer:** Hey, Any ideas why i'm still having major lobby issues on XB1? Wired connection Nat type 2 (open) what else can I do.
- `1529692` · first contact
  - **customer:** yo Xbox how come half of my friends can't get online and none of us can use party chat

### `install_download_update`

Getting software onto the console fails or stalls: game or app downloads and installs, disc installs, system updates, storage, or content that has to be re-downloaded.

- **Include:** 'Installation stopped', downloads stuck or slow, queue problems; Console or game updates that fail, loop or error; Games deleted or needing reinstall after an update; storage-full errors; Disc games that won't install
- **Exclude:** Installed content that crashes or won't start → `software_game_app`; Owned content the store won't let the customer get → `entitlements_subscriptions_codes`; The disc drive not reading any disc → `hardware_devices`
- **Response strategy:** Give install and update troubleshooting (clear local storage, offline system update, cancel and reinstall, check storage and the queue), or point to a known publisher-side issue.
- **Default risk:** `low`. **Default escalation:** Auto (ROUTINE_TROUBLESHOOTING). Escalate (STEPS_FAILED) when the standard steps have already failed, e.g. an update that bricked the console.
- **Examples:**
- `903420` · first contact
  - **customer:** Guys I'm having major issues installing games on my Xbox One, Keep getting Installation stopped, but there's space on drive
- `805812` · first contact
  - **customer:** xbox one s wont update. It downloads and verifys then restarts and process starts over.
- `1236555` · first contact
  - **customer:** Fall updated deleted some of my games requiring a re-download and install again. (over 200GB) Some games are just missing. :(

### `hardware_devices`

A physical device misbehaves: console power, shutdowns, heat or noise, disc drive, display/HDMI, controllers, headsets, Kinect, external storage. Also repair, warranty and replacement. Controllers stay here; their subtype is internal.

- **Include:** Console won't power on, shuts down, has no signal, green dots, fan noise; Disc drive won't read discs or scratches them; Blu-ray playback errors that point at the drive; Controllers that won't pair, disconnect, desync, or have faulty buttons; headset and mic problems; External drives not detected; device registration and warranty
- **Exclude:** One game or app freezing while everything else works → `software_game_app`; Wrong item in the box, delivery or retailer problems → `purchases_billing_orders`
- **Response strategy:** Give device troubleshooting (power cycle, another outlet, re-pair and update the controller, check the drive). If the device is faulty, route to the online repair or replacement process.
- **Default risk:** `medium`. **Default escalation:** Auto for first-line steps (ROUTINE_TROUBLESHOOTING), including a bare 'it broke' with no request: give the steps and ask for the symptom. Escalate (ACCOUNT_SPECIFIC) when the customer asks for a repair, replacement, warranty or servicing, or a repaired or replaced device still fails. Escalate (STEPS_FAILED) when the first-line steps have already failed.
- **Examples:**
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

### `software_game_app`

Installed software misbehaves: a game or app crashes, won't launch or has a bug; dashboard/UI problems after an update; app features such as notifications, messaging, streaming and achievements. Merged for v1.

- **Include:** A specific game or app crashes, freezes, won't open, or shows an error code; Dashboard/Guide UI broken or slow after an update; notifications, messages, keyboard; Achievements not unlocking; in-game content or credits missing because of a bug; Store or Xbox app crashing (the app itself, not a purchase)
- **Exclude:** Download or installation failures → `install_download_update`; Can't reach Live or game servers → `connectivity_xbox_live`; Paid content missing → `entitlements_subscriptions_codes`
- **Response strategy:** Give app or game troubleshooting (power cycle, remove and re-add the profile, uninstall and reinstall, check whether the console is in the Insider preview). Point to the developer or publisher for game-side bugs and patches.
- **Default risk:** `low`. **Default escalation:** Auto (ROUTINE_TROUBLESHOOTING). Escalate (STEPS_FAILED) when the steps have already failed; OUT_OF_SCOPE (developer) for patch timelines.
- **Examples:**
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

### `account_access_profile`

The customer's Microsoft/Xbox account itself: signing in with their credentials, recovery, creation, email/alias, gamertag, child/adult and family settings, profile data. A compromised account is this intent, with the SECURITY risk rule on top.

- **Include:** Can't sign in to *my* account, password or email recovery, account creation errors; Gamertag changes and availability, email alias, tenure or profile data; Child account rules and family settings; Account hacked or used by someone else (the SECURITY rule applies)
- **Exclude:** Service-wide sign-in outages → `connectivity_xbox_live`; Home Xbox and licences → `entitlements_subscriptions_codes`; Another player's conduct → `enforcement_safety`
- **Response strategy:** Link the self-service guide (recovery, alias, gamertag, family settings). Fixes that touch the customer's own account need identity verification, so hand off to chat or phone support.
- **Default risk:** `medium`. **Default escalation:** Escalate (ACCOUNT_SPECIFIC) when the fix needs someone to see or change this customer's own account (sign-in failures on their account, linked accounts, gamertag or profile changes that fail), which is most cases. Auto (GENERAL_INFO) for general how-to or policy questions such as child-account rules.
- **Examples:**
- `1678269` · first contact
  - **customer:** can’t sign in still or use any apps I even restarted my system and now can’t fully get my account back. It’s been 4 days now
- `1706513` · first contact
  - **customer:** I’m trying to make an account on Xbox and it keeps telling me that there is a problem?
- `345595` · follow-up
  - _customer_: my sons Xbox live account uses my wife’s email address. How can I change it to his own email address that I made for him?
  - _brand_: Hiya! To change the email that is associated with the account, let's have you follow the steps here: <URL>
  - **customer:** Will it cause my wife’s email account to be deleted? Asking as it wants me to create an alias and delete her address.

### `purchases_billing_orders`

The money or the order: purchases that fail, unexpected or duplicate charges, refunds, pricing and sales, pre-order deliveries, wrong items, retailer problems. Kept separate from entitlements.

- **Include:** Purchase fails with a payment error; payment method problems; Charged twice or unexpectedly; refund requests; sale price not honoured; Pre-order delivery or shipment; wrong item in the box; retailer issues
- **Exclude:** Paid, but the game, membership or code isn't showing → `entitlements_subscriptions_codes` (T5); Policy questions with no problem ('why does a free game need a card?') → `product_info_feedback`
- **Response strategy:** Acknowledge, share generic tips if relevant (check the payment info, try the web store), then route charges, refunds and orders to billing/chat support, and retailer orders to the retailer.
- **Default risk:** `high`. **Default escalation:** Always escalate (BILLING_DISPUTE for charges and refunds, otherwise ACCOUNT_SPECIFIC). Generic tips may go in the reply, but a person owns the case.
- **Examples:**
- `917784` · first contact
  - **customer:** This is what it says when I'm trying to buy the Friday the 13th 8 movie collection. HELP <URL>
- `941532` · first contact
  - **customer:** I'm having an issue with buying the Friday the 13th 8-Movie collection. Getting HRESULT: 0xc33507d1 CV: y1SY3VcE/kiJaJxH.48
- `23503` · first contact
  - _brand_: Have an Xbox support question & haven't heard back from us yet? Send another tweet our way if you need help!
  - **customer:** I’ve been charged twice for Star Wars battlefront 2

### `entitlements_subscriptions_codes`

Something the customer is entitled to isn't recognised or delivered: Gold / Game Pass memberships and trials, code or gift-card redemption, DLC and pre-order bonuses, owned games missing, licences, Home Xbox, game sharing. Merged for v1.

- **Include:** Gold or Game Pass bought or active but not recognised; trial questions; Codes or gift cards that won't redeem; beta or early-access codes; Pre-order bonuses, DLC or season-pass items, or purchased games missing from the library; Home Xbox changes, game sharing, licences for owned games
- **Exclude:** Payment failures, double charges, refunds → `purchases_billing_orders`; Bare error codes unrelated to redemption → `software_game_app` / `connectivity_xbox_live`
- **Response strategy:** Give entitlement troubleshooting (check subscriptions and order history, remove and re-add the profile, power cycle, follow the redemption guide). Hand off if it's still missing.
- **Default risk:** `medium`. **Default escalation:** Auto for first-line steps (ROUTINE_TROUBLESHOOTING). Escalate (ACCOUNT_SPECIFIC) when a specific order, code, charge or licence has to be looked up. Escalate (STEPS_FAILED) when the steps have already failed.
- **Examples:**
- `1649377` · first contact
  - **customer:** Preordered COD WW2 and I️ have the preorder bonuses installed but haven’t received them in game plz help
- `2300747` · first contact
  - **customer:** can u help me please i bought a 12 month abonnement and i cant play in live because it tells me i need to buy an abonnement i dont understand... <URL>
- `1410288` · first contact
  - **customer:** My redeem a code doesn't work, it keeps telling me to wait a bit but I've waited all day and still says the same thing

### `enforcement_safety`

Suspensions, bans and enforcement messages; reports of other players' conduct (harassment, threats, cheating); code-of-conduct questions; content rejected by moderation.

- **Include:** 'Why was I banned or suspended?', appeals, enforcement notices; Reporting another player, harassment, 'why wasn't action taken?'; Rejected gamerpics or content; code-of-conduct questions
- **Exclude:** The customer's own account being hacked → `account_access_profile`; Anger at support with no enforcement topic → `support_process_complaint`
- **Response strategy:** Use the fixed policy reply: support can't discuss or influence enforcement; point to the enforcement site and case review, and explain how to report players. Never speculate about an outcome.
- **Default risk:** `medium`. **Default escalation:** Auto with the policy template (GENERAL_INFO). The SAFETY_LEGAL rule escalates threats of harm, minors at risk and doxxing.
- **Examples:**
- `1298728` · first contact
  - **customer:** kinda fed up of Xbox as a company now they have banned me for the 4th time now stupid and each time is 2 week bans
- `891188` · first contact
  - _brand_: Have Call of Duty: WWII pre-ordered? Make sure your payment info is accurate here: <URL>
  - **customer:** Xbox my brother sent a message calling someone a tryhard and we got this message. Is this a warning or does it give us a punishment. <URL>
- `1531834` · first contact
  - **customer:** why am I not aloud to have any custom gamer pics all I had a was an image of Dva from @user it wasn’t even sexual wtf 😪

### `product_info_feedback`

Questions about how things work or what's available, and feedback or feature requests: specs, compatibility, backward compatibility, setup, how-tos, availability, policies, suggestions, negative opinions on design or updates. Questions and feedback stay merged.

- **Include:** How-to and 'does X support Y' questions (1080p streaming, external SSD, setup without internet); Backward-compatibility and content availability requests; Feature requests and negative opinions on design or updates; Policy questions (why a payment method is needed, trial limits in general)
- **Exclude:** The customer reports that something is failing → the matching issue intent (T10); Praise with no request → `social_offtopic` state (S2)
- **Response strategy:** Answer the factual question from the knowledge base. For suggestions, thank the customer and point to the feedback site. Never speculate on release dates or the roadmap.
- **Default risk:** `low`. **Default escalation:** Auto (GENERAL_INFO). OUT_OF_SCOPE when the answer belongs to a third party (a publisher or retailer).
- **Examples:**
- `1595815` · first contact
  - **customer:** The Xbox One X has faster load times from the internal HDD. Will I still benefit from using an external SSD?
- `1376297` · first contact
  - _other_customer_: been saying they should do this for years.. also this just exposed the kellyanne conway of the youtube world for "alternative facts" ;) <URL>
  - _customer_: Works for Destiny. And in 2017 how many people really don't have internet if they own a 4th gen console? Even for updates if not playing OL
  - _other_customer_: Best Destiny is a persistent online game. CoD SP doesn't require an active internet connection. I do agree it shouldn't effect most though.
  - **customer:** Doesn't XBOne require an internet connection to set up or update? Or have I mis-remembered again?
- `1769680` · first contact
  - **customer:** How can I stream in 1080p on Mixer on Xbox One, I have the 2017 Xbox Fall Update

### `support_process_complaint`

The message is mainly about the support experience, not a product problem: unanswered or repeated contacts, rude or unhelpful agents, demands for a human or another channel, general 'no one helps'.

- **Include:** 'Still waiting for help', 'chatted 4 times, still no solution'; Complaints about an agent or phone support; 'are you going to help me or not?'; Asks for another channel because the offered one doesn't work for them
- **Exclude:** A complaint that names a concrete product issue → that issue's intent, with the REPEAT_CONTACT / HIGH_ANGER risk rules; Anger about bans → `enforcement_safety` (T8); Vague help requests without a complaint about support → `needs_more_context` (T9)
- **Response strategy:** Apologise, acknowledge the history, ask for the one missing detail or offer the right channel, and hand the case to a person.
- **Default risk:** `high`. **Default escalation:** Always escalate (REPEAT_CONTACT, or HIGH_ANGER when no repeat contact is stated).
- **Examples:**
- `414172` · first contact
  - **customer:** Chatted in 4 times still no solution @user @user @user And no answer on my forum post! <URL>
- `1370514` · first contact
  - **customer:** just because he can’t understand what I tell him doesn’t mean he can be an ass
- `1451336` · follow-up
  - _customer_: Furious @user phone support,very rude hanging up the phone several times. Not customer service you would expect or except.
  - _brand_: Apologies for any frustrations, if you wish, we could help troubleshoot with you!
  - **customer:** Us a customer/consumer have rights

### `needs_more_context`

Even with the available thread context, the support issue can't be determined confidently enough to act.

- **Include:** A bare help request, image or link only: 'Any ideas or help? <URL>', 'Hello? Need assistance'; 'Having the same issues too' with no thread to inherit from; A pointer to an earlier question that isn't in the data; frustration with a screenshot only
- **Exclude:** Follow-ups whose issue is in the context → the thread's intent (`issue_followup`); Complaints about support itself → `support_process_complaint` (T9)
- **Response strategy:** Ask exactly one targeted clarifying question that names the missing detail (e.g. 'Which console, and what exact error text do you see?'). Never send a generic reply or a guess.
- **Default risk:** `low`. **Default escalation:** Auto: the clarification is sent (GENERAL_INFO). Escalate (LOW_CONFIDENCE) if the brand has already asked this customer for clarification in this thread. Untested on dev: no dev item was vague after a clarification.
- **Examples:**
- `743704` · first contact
  - **customer:** Any ideas or help? <URL>
- `899017` · first contact
  - **customer:** Hello? Need assistance ffs
- `2264062` · first contact
  - **customer:** having the same issues too I reset and delete and reinstall <URL>

## Tie-break rules (deterministic, in order)

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

## Risk and escalation rules

_Escalation policy status: **FROZEN**._

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
| `repeat_contact` | Says they already contacted support about this issue (DM, chat, phone, an earlier unanswered tweet) or have waited days. Raises the risk only; it doesn't escalate on its own. | `prior_contact`, `repeat_contact_cue` (partial) | `medium` | `REPEAT_CONTACT` |
| `steps_failed` | Says the standard first-line fix for this issue was already tried (by themselves or as advised) and the problem persists. Escalates on every intent; the reason is REPEAT_CONTACT if a repeat contact is also stated. | `repeat_contact_cue` (partial) | `medium` | `STEPS_FAILED` |
| `strong_anger` | Profanity, insults or abuse aimed at Xbox or support, or a threat to leave. Frustration, sarcasm, an angry emoji or disputing a decision alone don't count. | `anger` | `medium` | `HIGH_ANGER` |

- **FROZEN (2026-09-11)** after calibration on the 40-item dev set (`results/escalation/dev_calibration.md`).
- `risk_level` = the highest of the primary intent's default risk (`low` for states without an intent) and the risk of every rule that fires.
- `escalate = yes` if any of these hold:
- (a) `risk_level` is high.
- (b) The intent is `purchases_billing_orders` or `support_process_complaint` (always).
- (c) Account or entitlements, and the fix needs this customer's own account, order, code or licence (ACCOUNT_SPECIFIC).
- (d) Hardware, and a repair, replacement, warranty or servicing is requested, or a repaired or replaced device still fails (ACCOUNT_SPECIFIC).
- (e) `steps_failed` fires, on any intent (REPEAT_CONTACT if `repeat_contact` also fires, else STEPS_FAILED).
- (f) `strong_anger` fires on an intent whose default risk is medium or high (HIGH_ANGER).
- (g) It's `needs_more_context` and the brand already asked this customer for clarification in the thread (LOW_CONFIDENCE).
- (h) Phase 7: the classifier's confidence is below the threshold set on dev (LOW_CONFIDENCE).
- (i) System only: the drafted reply fails validation after its retries (REPLY_FAILED_CHECKS).
- `repeat_contact` alone does not escalate; it only raises the risk level.
- `reason_code`, when escalating, is the first match in this order: SECURITY > SAFETY_LEGAL > BILLING_DISPUTE > ACCOUNT_SPECIFIC > REPEAT_CONTACT > STEPS_FAILED > HIGH_ANGER > OUT_OF_SCOPE > LOW_CONFIDENCE > REPLY_FAILED_CHECKS. When not escalating: ROUTINE_TROUBLESHOOTING for fixes, GENERAL_INFO otherwise.
- Cue `prior_clarification`: the brand asked this customer for missing details earlier in the thread. Brand announcements, answers and troubleshooting steps don't count.
- These rules apply on top of any intent or state. There are no intents for hacked accounts, anger or threats.
- Phase 2's `customer_escalation_signals` (keyword cues) map onto these rules as shown in the signal column. They are weak hints only; the labeller decides.

## Escalation calibration (dev set)

**Status:** done. The policy above was calibrated on the dev set and frozen on 2026-09-11. The full comparison is in `results/escalation/dev_calibration.md` (`scripts/calibrate_escalation.py`); `DECISIONS.md` records the changes.
**Dev set:** 40 holdout exchanges, one per thread, all eval-eligible: 16 random and 24 targeted (4 per behaviour below). Drawn blind by `scripts/sample_dev.py` into `data/golden/dev_labeling_sheet.csv`. Dev is used for tuning only. It is never reported, never used for few-shot examples, and never put in the index.
**Labels:** ChatGPT drafts made with this codebook, reviewed and approved item by item by the project owner. They are not blind human labels (see `DECISIONS.md`). Fixes made after review are recorded in each item's notes.
**Procedure:** the draft rules were applied to the labelled intents and cues and compared with each item's `escalate` label. A rule was changed only where the dev evidence disagreed.
**Result:** the draft as written agreed with 37 of 40 labels; the frozen policy agrees with all 40. The one change in behaviour splits `steps_failed` out of `repeat_contact`, so failed steps escalate on every intent (D26, D31, D35). The other changes only tighten the wording.
**Behaviours:**
- `strong_anger`: unchanged; it escalates only medium- and high-risk intents. No dev item had anger on a low-risk intent.
- `repeat_contact`: on its own it does not escalate (D01); failed steps do.
- Account-specific handling: escalate when this customer's own account, order, code or licence is needed; how-to stays auto. The auto side is untested on dev.
- Low-confidence escalation: a threshold on the classifier's confidence, set on dev in Phase 7.
- `needs_more_context` after a prior clarification: escalate. Untested: no dev item was vague after a clarification.
- Repair / replacement: escalate on an explicit request or after failed steps; a bare 'it broke' stays auto. Dev can't separate the two triggers, because every repair item also had failed steps.
**Next:** sample and label the 200-item golden set from the holdout, excluding every dev thread.

## How labels are scored

How the golden set will be scored (`src/eval`, Phase 9). Every metric gets a bootstrap 95% CI and is reported separately for the random and stratified slices.
- **Conversation state:** accuracy and macro-F1 over the 4 states, on all items.
- **Intent:** macro-F1 over the 11 intents, **conditional on intent-bearing states**: only items whose gold state is `new_issue` or `issue_followup`. A missing or extra intent prediction counts as an error. Also reported: per-intent precision, recall and F1, and the confusion matrix.
- **Escalation:** precision and recall of `escalate = yes` on all items. **Must-escalate recall** is the recall on items whose gold `risk_level` is high or whose gold reason is SECURITY, SAFETY_LEGAL or BILLING_DISPUTE. This is the safety metric.
- **Joint routing correctness:** the share of items where the state is right, the primary intent is right (when the gold state carries one), and `escalate` is right, all at once.
- **Never scored:** `secondary_intents`, `subtype`, `event_tag`. `reason_code` agreement is reported for information only.
- **Analysis slices:** first contact vs follow-up, and event-tied vs not, where event tags were noted.

## Internal fields (never scored)

- `secondary_intents`: the other intent(s) of a multi-issue message (T0 picks the primary).
- `subtype`: `hardware_devices` → `console`, `disc_drive`, `display_output`, `controller_accessory`, `external_storage`; `software_game_app` → `game`, `app`, `dashboard_system`; `entitlements_subscriptions_codes` → `membership`, `code_redemption`, `dlc_bonus_content`, `purchased_item_missing`, `licence_home_sharing`
- `event_tag`: `fall_update_2017`, `cod_wwii_launch`, `battlefront2_launch_beta`, `xbox_one_x_launch`, `xbox_live_outage`, `friday13_movie_sale`, `hurricane_maria`

## Summary table

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
