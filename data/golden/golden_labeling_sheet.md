# Golden labelling sheet (200 items)

_Write labels in `golden_labeling_sheet.csv`, one row per item, using the frozen codebook. Use the context and the message only: the historical brand reply is deliberately not shown. **Don't look at any Claude or ChatGPT labels for these items until all 200 are done** (protocol: `LABELING.md`). Don't reorder rows or edit the IDs._

## Quick reference (frozen codebook v1; the full rules and examples are in `data/codebook.md`)

**Scored: fill these for every item.**

- `conversation_state`: `new_issue`, `issue_followup`, `acknowledgement_closing`, `social_offtopic`. Leave `intent` blank for `acknowledgement_closing`, `social_offtopic`.
- `intent`: exactly one primary intent (T0 picks it when a message raises several issues).
- `escalate`: `yes` / `no`, from the escalation rules below.
- `label_confidence`: `high` / `medium` / `low`.

**Optional reference columns** (never scored; fill them only if they help you): `secondary_intents`, `risk_level`, `reason_code`, the `cue_*` columns (`yes` / `no`) and `notes`.

**States**

- `new_issue`: The message raises a support issue this customer hasn't already raised in this thread. This includes replies to brand announcements and to other customers' tweets.
- `issue_followup`: The message continues a support issue this customer already raised in the thread, or answers the brand about it: details, 'tried that', 'still broken', 'are you going to help?'. Promises to try something or report back ('will try tonight', 'I'll get back to you') are also follow-ups, because the issue is still open. It takes the thread's issue as its intent.
- `acknowledgement_closing`: The customer thanks the brand, confirms the issue is fixed, or says okay, **and no unresolved support issue remains**. Nothing new is asked, and nothing is pending on the customer's side.
- `social_offtopic`: No support request at all: praise, banter, self-promotion, tweets that only tag the brand.

**Intents**

- `connectivity_xbox_live`: The customer can't reach Xbox Live or a game's online service, or their online session is unstable: service sign-in, disconnects, lag, NAT, party chat connection, game servers, or 'is Live down?'.
- `install_download_update`: Getting software onto the console fails or stalls: game or app downloads and installs, disc installs, system updates, storage, or content that has to be re-downloaded.
- `hardware_devices`: A physical device misbehaves: console power, shutdowns, heat or noise, disc drive, display/HDMI, controllers, headsets, Kinect, external storage. Also repair, warranty and replacement. Controllers stay here; their subtype is internal.
- `software_game_app`: Installed software misbehaves: a game or app crashes, won't launch or has a bug; dashboard/UI problems after an update; app features such as notifications, messaging, streaming and achievements. Merged for v1.
- `account_access_profile`: The customer's Microsoft/Xbox account itself: signing in with their credentials, recovery, creation, email/alias, gamertag, child/adult and family settings, profile data. A compromised account is this intent, with the SECURITY risk rule on top.
- `purchases_billing_orders`: The money or the order: purchases that fail, unexpected or duplicate charges, refunds, pricing and sales, pre-order deliveries, wrong items, retailer problems. Kept separate from entitlements.
- `entitlements_subscriptions_codes`: Something the customer is entitled to isn't recognised or delivered: Gold / Game Pass memberships and trials, code or gift-card redemption, DLC and pre-order bonuses, owned games missing, licences, Home Xbox, game sharing. Merged for v1.
- `enforcement_safety`: Suspensions, bans and enforcement messages; reports of other players' conduct (harassment, threats, cheating); code-of-conduct questions; content rejected by moderation.
- `product_info_feedback`: Questions about how things work or what's available, and feedback or feature requests: specs, compatibility, backward compatibility, setup, how-tos, availability, policies, suggestions, negative opinions on design or updates. Questions and feedback stay merged.
- `support_process_complaint`: The message is mainly about the support experience, not a product problem: unanswered or repeated contacts, rude or unhelpful agents, demands for a human or another channel, general 'no one helps'.
- `needs_more_context`: Even with the available thread context, the support issue can't be determined confidently enough to act.

**Risk rules**

- `account_compromised` → high: Someone else is using or has taken the account; hacked; unauthorised sign-ins or purchases.
- `harm_or_legal` → high: Threats of violence or self-harm, minors at risk, doxxing; lawsuits, police, lawyers, regulators.
- `money_dispute` → high: Charged twice or without consent, refund refused, money taken.
- `repeat_contact` → medium: Says they already contacted support about this issue (DM, chat, phone, an earlier unanswered tweet) or have waited days. Raises the risk only; it doesn't escalate on its own.
- `steps_failed` → medium: Says the standard first-line fix for this issue was already tried (by themselves or as advised) and the problem persists. Escalates on every intent; the reason is REPEAT_CONTACT if a repeat contact is also stated.
- `strong_anger` → medium: Profanity, insults or abuse aimed at Xbox or support, or a threat to leave. Frustration, sarcasm, an angry emoji or disputing a decision alone don't count.

**Escalation (frozen)**

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

## Items

**G001** · `118373` · follow-up
  - _customer_: my gamertag was changed for no reason, when I went to add live to it it went from "sl1ck sp1c57" to "broadcolt275476". Still have my cod stats though.
  - _customer_: It told me that I had changed it 3 days ago, I only changed my name once and it was to sl1ck sp1c57. I removed the previous tweeted pic, my friends name was in it.
  - _brand_: Have you checked the email associated with your Xbox account for any emails from the Enforcement Team that could be the reason you had a forced Gamertag change?
  - **customer:** I just did. There's no email in the account and at least if I can't get that id like to change it to something better than "broadcolt".

**G002** · `99058` · first contact
  - **customer:** i’ve tried almost everything help @user <URL>

**G003** · `169146` · first contact
  - **customer:** I have been comm banned for 2 weeks, WHY, its double rep weekend on 2K and im on break ya'll need to explain why enforcement banned me

**G004** · `2737529` · first contact
  - **customer:** Hey @user I've been in two chat sessions about a compromised account/forgotten password and they both said they would get back to me via email, and they haven't. I'm really angry..

**G005** · `2858533` · follow-up
  - _other_customer_: I'm totally on board for the "Haunted Xbox One" thing.... @user why does my xbox randomly turn on by itself?
  - _customer_: Can we get an answer to this please. I've been asking this for a year now.
  - _brand_: Hello! Would you mind letting us know if your console is plugged into a wall outlet or a power strip?
  - **customer:** It's plugged into a power strip.

**G006** · `545523` · first contact
  - **customer:** hi! My Xbox One X is very loud when playing Battlefront II. Any suggestions? I'm playing on a 4K HDR TV, if that makes any difference.

**G007** · `570265` · follow-up
  - _customer_: I keep on gettimg this error message while tryimg to buy Sonic Adventure 2 on the Xbox One. I really want to play it Need Help to fix this problem <URL>
  - _brand_: Heya! Are you able to make that purchase here <URL>
  - **customer:** No I cannot, it gives me the same message <URL>

**G008** · `565143` · follow-up
  - _customer_: I'm just going to keep tweeting @user @user @user until this is resolved. Should have gotten my Xbox 11/28. 9 days since my order, 5 since I should have had it, 2 since I should have been called by CS. Nothing but lies and empty promises.
  - _brand_: Official Xbox Support here! We'd be happy to help you try and few things or point you in the right direction for help.
  - **customer:** Will unless you plan on overnight shipping me an Xbox One X, there isn't much you can do. I ordered a console over a week ago, it was marked shipped over a week ago, and the post office never received it. Customer Support has done nothing to resolve

**G009** · `450506` · first contact
  - **customer:** I got suspension because a player on Rainbow Six Siege got mad at me. He proceeded to tell me I would get a "COM Ban" nothing had happened the day he said this. But today when I went to chat in a party with my friends it wouldn't let me. My Gt is "AtomicBrace"

**G010** · `2713685` · first contact
  - **customer:** y’all @user app is trash

**G011** · `1125226` · follow-up
  - _customer_: From @user "happy Thanksgiving, have a non existent error code and no network connection for fun!" @user @user #XboxOne #Xbox <URL>
  - _brand_: Hello, when did this code appear when you were using the console? You can use these steps to power cycle your console to help resolve the issue you are experiencing <URL>
  - **customer:** Power cycled it several times. Any idea what the error code means?

**G012** · `505523` · first contact
  - **customer:** my xbox one controller wont connect.to to the console when I try to sync it, why is this?

**G013** · `2897779` · follow-up
  - _customer_: hey @user me and @user's shared xbox account got hacked and the details were changed :( can you PLEASE help us retrieve our account!?
  - _brand_: Howdy! If you think your account has been compromised, check out this page: <URL> for info & next steps.
  - **customer:** ny account was hacked AND banned, and we dont have any details.

**G014** · `153152` · first contact
  - **customer:** will a normal xbox one look better on a 4k tv or only the xbox one x

**G015** · `2630775` · first contact
  - **customer:** Gotta say, Christina M at @user chat #greatcustomerservice

**G016** · `863781` · follow-up
  - _customer_: I was billed for EA Access, but when I go to my games and apps, it is not showing up as a membership. If you look under settings, it is showing up as a membership. I called in before and went through troubleshooting, but no luck. EA has not been responsive.
  - _customer_: My gametag is The Makr. Issue started when I upgraded from my day one xbox to the new Xbox One X. It seems to be occurring because you guys are recognizing my membership via account, but EA is looking for my old machine?
  - _brand_: Thanks for that info! Are you able to confirm the correct spelling of your gamertag is: The Makr.
  - **customer:** Yes, that is me. I've been on Xbox Live for many years. I own 3 Xbox ones. Big fan of your services, but I do need this somehow resolved since I have been billed for EA Access. My son already missed the week of early access to Battlefront 2. He preordered it.

**G017** · `183202` · first contact
  - **customer:** Having an issue with my headset/controller. But I doubt you guys will reply :/

**G018** · `2972564` · first contact
  - **customer:** i keep getting this same error code every attempt I make to connect to my one buddy. No issues with any other person but him and it just started a week ago. Your 'customer support' line was useless and told me that not even a real code. Im about to buy a PS4 <URL>

**G019** · `521452` · first contact
  - **customer:** I can't connect my bluetooth controller to my phone my phone is a lg and its not working can you tell me how to pair it to my phone?

**G020** · `2585935` · first contact
  - **customer:** Hello, I have a few concerns regarding my Xbox One X. Could you please help? Thank you.

**G021** · `2518613` · first contact
  - **customer:** I can’t launch Fortnite and keeps telling if I own a disc or an online version and I know I have played it about a week ago and now I can’t

**G022** · `621204` · follow-up
  - _customer_: hi I’m trying to reinstall battlefield 4 ok and it only gets to 44% and won’t go any further I’ve restarted twice and uninstalled and reinstalled twice also
  - _customer_: A physical copy
  - _brand_: Gotcha. In this case, we'd recommend following the steps here: <URL>
  - **customer:** The disc loads 46% then it says installation stopped

**G023** · `513855` · first contact
  - _other_customer_: hello! I had a problem with my xbox account, my friend deleted my main xbox live account and i have no idea what is my email anymore, i only remember my gamertag, can you help me?
  - **customer:** pede pra deus amigo ou pro bolsonabo

**G024** · `2754929` · first contact
  - **customer:** bought wwe2k18 season pass last month. Now I can't download the new content it's trying to make me buy it again!!

**G025** · `123850` · follow-up
  - _customer_: Help please! My Kinect won't turn on my #XboxOneX console. It works properly for all other functions... <URL>
  - _customer_: Whole thing.
  - _brand_: Got it. Definitely odd. One thing that would be worth trying is unplugging the Kinect adapter then factory resetting the console keeping your games and apps: <URL> . Keep us in the loop.
  - **customer:** One other thing: The Kinect actually powers down when the console turns off - it didn't do that with my old Xbox.

**G026** · `2957235` · first contact
  - **customer:** can you tell me what the update entails that I downloaded this morning? Since your support team has no idea about the preview program updates <URL>

**G027** · `2842209` · follow-up
  - _customer_: can xbone x play online with xbone users? (COD WWII)
  - _brand_: Hey there, can you please DM us with a full description of the issue you are having along with your Gamertag? Please include verbatims of any error you are seeing.
  - **customer:** No issue, just checking if I’ll be able to play with my buddies if I switch to a one s/x and they stay at Xbox one?

**G028** · `54429` · follow-up
  - _customer_: Hi. Tried these steps. I can hear the audio it's the Mic that is not responding. I tried an alternative headset and this worked both on Mic and headphones
  - _brand_: Got i, it would be worth it to try these steps: <URL> and the skype test at the end. If nothing there as well it would be worth it to reach out here: <URL> for service options.
  - **customer:** Hi. I have emailed my proof of purchase as requested on the 23rd and still have not heard back from your support team. Chased again earlier today. Can you update please

**G029** · `565199` · first contact
  - **customer:** Seriously, don’t get an @user you can’t even plan a dvd. It’s basically a clown box since it can’t do anything. #fuckxbox #getplaystation

**G030** · `1719961` · first contact
  - **customer:** I get a message saying ''Your Xbox profile setting for voice and text are preventing you from using the chat. Go to <URL> to change your settings''. However everywhere i look i can't change my settings. Can you help me so that I can type in games?

**G031** · `2654476` · follow-up
  - _customer_: hey, my copy of COD WWII said its refunded and my brother bought it before it was released. I was playing it for the past 3 weeks and it doesnt wanna work.
  - _brand_: Hello! If the game is showing refunded then you will need to purchase the game again to be able to play it.
  - **customer:** But why pay if i already bought it..

**G032** · `2747533` · first contact
  - **customer:** the Xbox 360 was amazing but the Xbox One is the biggest piece of shit I've ever owned

**G033** · `95023` · follow-up
  - _customer_: I have 23Mb/s download but on my Xbox one it only says <3Mb/s. Upload is higher too. I am wired, tried wireless but it was the same problem Have restarted both modem and Xbox. Still the same problem
  - _customer_: My gamertag is Daancho, not sure how that will help but alright
  - _brand_: Thanks for that info. Please try the steps here: <URL> to see if there can help out with the slow downloads you're seeing on your Xbox One console.
  - **customer:** I've tried that. I'm still getting slow speeds in the detailed network statistics. It's showing I'm getting <2Mb/s down and about 4Mb/s up I think something may be wrong with my Xbox maybe??

**G034** · `2919017` · first contact
  - **customer:** Why is my Xbox 1 loud as shit the first 20 mins it’s on

**G035** · `2912012` · first contact
  - _customer_: Hello. I have a problem with my xbox one game. It brings me back to home screen while loading all the time. I know that there's something wrong with my profile. Could you fix that, please?
  - _customer_: Here you can see the problem. From my Xbox NHL works for other accounts, who has bought that game, but doesn't work for mine. Bought that game 2 days ago. I'm really disappointed. @user <URL>
  - _other_customer_: Gotcha, how about highlighting the game and hitting start and then going to Manage Game and clearing the save data for your gamertag? -Cade
  - **customer:** Huge thanks, now it works!

**G036** · `1292227` · follow-up
  - _customer_: hey Xbox support can I please get refund for Marvel heroes omega I bought a tons of stuff and now the game is shutting down?
  - _brand_: If you would like to inquire about a refund, you can reach out to our chat team here. <URL>
  - **customer:** No worries I already talked too then and they helped

**G037** · `522285` · first contact
  - _other_customer_: #CODWWII Ranked Play Season 1 starts tomorrow 12/1 at 10AM PT on PS4 and XB1. Details here: <URL> <URL> #CODWWII Ranked Play Season 1: The Placement Season is now LIVE! Get out there and grind for that Pro Helmet! <URL>
  - _brand_: Official Xbox Support here. Are you still having trouble on the Xbox console? If so could you tweet us more details? We'd love to help.
  - _customer_: I’m still being put on terrible teams when I have a higher score per min and the servers tend to crash non stop on call of duty ww2
  - **customer:** And my console tends to freeze once said digital games are launched

**G038** · `2818611` · first contact
  - **customer:** I get an error "your purchase cannot be completed" everytime I try to buy persona 4 arena (backwards compatible) from my Xbox one. I tried buying another free backwards compatible title and the error did not suffice. What is the fix for this?

**G039** · `519474` · first contact
  - _other_customer_: You also get to vote for which map/mode before the Ranked match starts. <URL> <URL>
  - **customer:** xbox isn't working

**G040** · `2860248` · follow-up
  - _customer_: can someone tell me why every time I play Survival on MW3 why does my rank get reset to 1? In my barracks it shows my highest was a 48 and another as 45. Is there a fix in this? My multiplayer rank and prestige is okay it’s just the Special Ops - Survival...
  - _brand_: Hey there! For this issue, we'd recommend reaching out to the developer here: <URL>
  - **customer:** This site that was given directs me into newer type games such as ww2 ghost etc...

**G041** · `2698207` · first contact
  - **customer:** why does my Fifa freeze on the load up screen all the time. This game was bought from the Xbox store

**G042** · `2732139` · follow-up
  - _customer_: Please help, my little cousins Xbox 360 Slim red ringed but only the center of the power button is red, no rings are lit up but whenever I turn it on this message pops up. <URL>
  - _brand_: Hi there! Have you been able to work through all the steps here: <URL>
  - **customer:** It also doesn’t prompt a system update or anything and has never been connected to Xbox live so the steps I’ve tried don’t work

**G043** · `2594918` · first contact
  - **customer:** So #xbox360 doesn’t support #ThursdayNightFootball via @user? What gives @user

**G044** · `463190` · follow-up
  - _customer_: I want my money back for Destiny 2 and Call of Duty WW2, I dont care about your policy im not giving anyone over $150 for games i dont even play that are brand new,2 new games not even 3 monthes old and they lack on developers part not the consumers
  - _brand_: Hi there! For assistance with Refunds let's have you check in with our chat teams here <URL>
  - **customer:** ive already spoken to someone last night about a refund for Destiny 2 and Call of Duty World War 2 i just want my money for both games back thats all then im never buying Bungie or Activsion games again

**G045** · `668438` · first contact
  - _brand_: If you are seeing an error while trying to play on Xbox Live, you’ll first want to check to make sure your subscription is in good standing: <URL>
  - _customer_: Yeah, question, I have Xbox live, you guys took it out of my account and every time I try to play a game, it gives me a screen asking to pay for Xbox live....
  - _other_customer_: same here
  - **customer:** And it’s so frustrating!

**G046** · `702357` · first contact
  - _brand_: Wondering what to do if you accidentally purchased a game? Check for next steps here: <URL>
  - **customer:** I can't refund it? <URL>

**G047** · `567806` · first contact
  - **customer:** my account has been hacked into

**G048** · `2508707` · first contact
  - **customer:** renewed gold live but can’t play online 😒 battlefront2 is out! Help please @user

**G049** · `565188` · first contact
  - **customer:** I can hear echos coming from this old piece of shit xbox

**G050** · `975522` · first contact
  - **customer:** I've been charged a different amount to what has been advertised on the store for a digital download. Help Please? ...

**G051** · `2654345` · first contact
  - **customer:** . My account is locked and wont let me update my billing information.

**G052** · `2710677` · first contact
  - **customer:** why cod ww2 was in the black friday deals cost 50$ and now back to 59.99$?

**G053** · `23436` · first contact
  - **customer:** For months now, my #iOS @user app gives the following error when I try to sign-in. Any ideas? <URL>

**G054** · `2896387` · first contact
  - **customer:** The xbox one x Scorpio edition can't hold a steady wifi connection to save it's damn life. I've had connectivity issues constantly since I've "upgraded" to this piece of shit. @user

**G055** · `2926569` · follow-up
  - _customer_: I got a message during call of duty from an opponent that simply said “reported” I can’t ask him why because I already have a communication ban. Can I DM someone about this because I better not get an extension on this. I saw this dude killing my teammates from said location and went up behind him by and eliminated him. I sat there long enough for him to try and get back into the spot and killed him again.
  - _customer_: No matter how I word it, it sounds like retaliation. I’ll probably get hit with yet another ban and I’m sure this one will be more severe. Just for protecting my objective.
  - _brand_: Just be sure to follow the code of conduct and you will not have to worry. If you know something is against the rules of the game don't do it. If it is not then you will not need to worry.
  - **customer:** So. What if the makers of Call of Duty decide to not fix this spot everyone is calling a “glitch”. Then is it still misconduct? They’ve had past maps where they intentionally left those spots accessible.

**G056** · `2899257` · first contact
  - **customer:** What is the highest storage does the Xbox One X support for external hard drives?

**G057** · `2920247` · first contact
  - **customer:** My account is saying I have no xbox live when I put 3 months on it last month before it was due to run out? Any help?

**G058** · `2511133` · first contact
  - **customer:** your company is soft as shit. Ban me for using adult words? Really? Can’t wait for your ceo to see my lawyers email this is bullshit I️ shouldn’t be paying for a service that bans me ON A RATED M GAME fuck off

**G059** · `2868605` · first contact
  - **customer:** random question. This month’s “quest” is to get 400 achievement points, login to Mixer 5 different days, download 2 games with gold. Well according to the monthly leaderboard I only have 95 points, cause Marvel Heroes Omega shut down, I had 170 this month from that So I guess my question is, how does that work? Do I need to now get 305 more points before the end of the month, or am I sitting at 265 like I actually have?

**G060** · `2875118` · first contact
  - **customer:** #MyFriend @user Was recently hacked! The hacker bought $164 worth of stuff. We have reasons to believe the hacker is @user

**G061** · `667611` · follow-up
  - _customer_: how can you communication ban someone for 2WEEKS. I pay 60$ a year to use your platform. This is ridiculous
  - _brand_: Hi. We're separate from Enforcement here and don't have suspension information available to us here on Twitter. We suggest submitting a case review <URL> if you're eligible.
  - **customer:** How long does case review take

**G062** · `2961531` · follow-up
  - _other_customer_: my Xbox keeps losing connection to the internet and when I go to reconnect it it keeps saying additional authentication needed, what is this?
  - _brand_: Hi there! Let's check out our guide here for this connection issue that you're seeing <URL>
  - **customer:** hi, is it possible to share a live direct from xbox on facebook during a playing session?

**G063** · `105851` · follow-up
  - _customer_: My friend and I have been having an issue with connecting to each other in an online party, the party works fine until we both are in it, how can this be fixed? Thank you
  - _customer_: <URL>
  - _brand_: Thanks for sending us this info. Are you encountering any specific error messages when you try to connect to party chat?
  - **customer:** Yes, everyone or just one of us starts connecting then either my friend that I’m having the problem with or I will disconnect then we keep joining and leaving

**G064** · `2579790` · first contact
  - **customer:** how do I initiate a digital refund?

**G065** · `1252649` · first contact
  - **customer:** hello I'm having trouble with backcompat. It won't even let me download free Xbox 360 games on my Xbox one. I have also tried uploading Xbox 360 games to my Xbox one which I have purchased on the system did not work please help

**G066** · `2740175` · first contact
  - **customer:** , I recently purchased Xbox One S and I've just found out that Xbox Live Gold is not supported in my country (Bulgaria). What should I do in order to play online multiplayer ?

**G067** · `863742` · first contact
  - _other_customer_: Hey @user, what is the earliest date for Marvel Heroes Omega refunds to be issues? Is it anything after 2017-07-01, or something earlier/later?
  - **customer:** They gave a full refund for all items purchased in game, except for a few that haven’t been approved for refund yet. Go on their website and go through support there. They were great about it. Have the order numbers.

**G068** · `2617433` · follow-up
  - _customer_: white controller packaged with Xbox one s is paired as it will function correctly for about 45 seconds and then while still appearing paired will stop responding. Tried power cycling and repairing. Been going on almost 12 hours Is there any chance of getting support
  - _brand_: Hi there! Let's be sure to work through all the steps here: <URL>
  - **customer:** This was one of the first things I did. None of the steps were successful. The controller functions correctly via Bluetooth to win 10 PC but not to any of my consoles

**G069** · `2654303` · first contact
  - **customer:** I'm having problems with the YouTube app on Xbox one when each time I press upload it crashes and signs me out of my account.

**G070** · `2708784` · follow-up
  - _customer_: can you explain why I cancelled my payment but use just took payment from me even when it's cancelled..........
  - _brand_: Hi there! We'd recommend reaching out to the chat team here: <URL> to discuss your options.
  - **customer:** Ok that didn't work what now

**G071** · `546900` · first contact
  - **customer:** , buying a new XB1s. How big is the update on 1st startup... Estimate?

**G072** · `120892` · follow-up
  - _customer_: I just saw the news article right now for this. Isn't this against TOS? People are going to unknowingly get themselves hurt. <URL> @user
  - _brand_: Not sure what your referring to but all official news can be found on <URL> . We couldn't speculate on any 3rd party sites.
  - **customer:** It's a site where you give someone your account info and pay them to play call of duty wwII for you to help you prestige faster.

**G073** · `564261` · follow-up
  - _customer_: do you guys have a automated Coms van system in place, I sent my friend a mildly offensive joking message that I’ve known for YEARS a message and shortly after got a 2 week coms ban? He wasn’t offended and he didn’t report me?
  - _customer_: Thanks that didn’t help or answer my question at all
  - _brand_: There is no automatic suspension as stated in the documents on the link our Ambassador shared. We do hope that helps clarify.
  - **customer:** Thanks, but why would I get banned for a message that I sent to my friend and didn’t get reported for? Was one of your workers just browsing my messages at that exact time?

**G074** · `175092` · follow-up
  - _customer_: so when do I receive a Credit for Music I purchased through Groove & no longer can play due to COPYRIGHT restrictions? Not on I'm seriously losing faith in @user & @user
  - _customer_: it STILL doesn't answer why music I have BOUGHT is unavailable now even though I own it so SURELY I should get it REFUNDED?
  - _brand_: Afraid we wouldn't be able to speculate about refunds on our end. For this, we recommend Reaching out to the live chat team to explore some possible options <URL>
  - **customer:** Thanx I'll try them & see if it can be resolved satisfactorily, fingers crossed. Hopefully U can understand my frustration. 👍

**G075** · `702394` · first contact
  - **customer:** I have completed 2 challenges for the Xbox game pass for this month and have not received the gift yet. Why have I not received it yet through the messages?

**G076** · `447532` · first contact
  - _other_customer_: When your @user One X already stops working right <URL>
  - _customer_: Better do it before Monday
  - _other_customer_: Well if that doesn’t work I can either ship it to them or go to a Microsoft store. But since WV sucks and nobody wants to open any stores here I’d have to go to Ohio or Virginia.
  - **customer:** Whenever I first got my Xbone it broke and I had to mail it back for repair

**G077** · `488311` · first contact
  - **customer:** so dont ban me i hit nice shots and the last kill was afk and this guys claims im hacking <URL> I have so many loses and i have never won idk what this kids problem is

**G078** · `564246` · follow-up
  - _customer_: plugging the usb cable i got with my headset in my controller and xbox causes my xbox to completely shut off. Any ideas as to why?
  - _brand_: Hi there! Does it do this with any USB cable you use? Can you test another cable for us?
  - **customer:** I tried the usb cable for my external hard drive and i got a message saying 'we see your external storage, but the connection is too weak to use'

**G079** · `2871789` · first contact
  - **customer:** I would like to refund my order of Fallout 4, would that be possible?

**G080** · `340459` · first contact
  - **customer:** Had the X for two weeks now and it's just constant problems. Games and Apps not loading up. Controller being unresponsive. Freezing in games. Doesn't matter if disc or digital, there are constantly problems. Worst 'new' console experience I've ever had! 'Do you own this game or app?' Yes I do! The disc is in there but the machine can't even see that. I'd have refunded but I stupidly spent money on games for this machine. In too deep now. Probably going to have to do a return and get a replacement. Which will result in another wait for your huge downloads (that are throttled by yourselves. Seriously, I get about 1/5 of my actual speed). /rant over

**G081** · `2528982` · first contact
  - **customer:** How do I turn this nonsense off? I already have notifications turned off in the settings. <URL>

**G082** · `2819967` · first contact
  - **customer:** Just bought a gift code using gifting on Xbox one (Wolfenstein 2) and it won't redeem for the recipient. Funny part is it won't redeem for me either.

**G083** · `2516434` · first contact
  - **customer:** I bought a pack for marvel heroes Omega on 10/27/2017. Game is shutting down out of nowhere. How do I get a refund? Feeling scammed.

**G084** · `2715726` · follow-up
  - _customer_: And the leaderbords are been hacked again.... Can someone please solve this minor problem so people ho are trying to achief somthing in a legit way don’t 💩themselfs from frustration anymore. Thanks @user @user
  - _brand_: Hi there! We'd recommend reaching out to the developer here: <URL>
  - **customer:** Hi, thanks for the feedback. Will check that out asap. Have a nice day 👍 Grtz

**G085** · `2916170` · first contact
  - **customer:** Went on xbox for game of fifa. one hour later still waiting...fucking updates thats all you ever get on this piece of shit😲😈

**G086** · `2923708` · first contact
  - **customer:** hello i need a number

**G087** · `2854021` · first contact
  - **customer:** is there anything Xbox can do to make my account an adult account, I'm 21

**G088** · `1352084` · first contact
  - **customer:** bought Xbox one with Minecraft. Is it supposed to have security stickers cut at bottom of box and new similar less protective stickers on top?

**G089** · `509881` · first contact
  - **customer:** the latest Xbox insider update has stuffed my Xbox, wtf am I meant to do? Any time I try go into an official I just get a message saying “something went wrong” error code 0x87dd001a I reset my console as I’ve read to do elsewhere and now I can’t even use it because it says it has to update but won’t update because of an error

**G090** · `241059` · follow-up
  - _customer_: any reason why I cant upload screenshots to my OneDrive? I downloaded the app. There's a whopping 25 pictures in it, so its not full. Always says "oops something went wrong."
  - _brand_: Hi there, does this happen with game clips as well or just screenshots? Have you setup your OneDrive account: <URL> for use with the same Microsoft account you have tied to your gamertag?
  - **customer:** I haven't tried clips. And I assume its connected. It worked fine until one random day.

**G091** · `121807` · first contact
  - _brand_: Thinking about making the jump to Xbox One X? Learn how you can pre-download 4K assets for Xbox One X Enhanced titles with this video: <URL>
  - **customer:** Is it the same as the Xb1 S?

**G092** · `1327687` · follow-up
  - _customer_: So I typed in my Xbox Live Gold 14 day trial, and when I type the code in, nothing happens, the keyboard stays up and says redeem code or gift card, with my code still in the bar however it won’t process it? Any help?
  - _brand_: Hello, would you be able to direct message us with your Gamertag, the code and where was it purchased so we can better assist you?
  - **customer:** Sorted it now, I had to re type it a few more times, but thanks for getting back to me

**G093** · `2705236` · follow-up
  - _customer_: I'm running around in circles trying to get a refund for a digital gift that i purchased online. I don't know what to do.
  - _brand_: Hi there! Are you able to see the option for that when you find the gift here: <URL>
  - **customer:** Sorry, that didn't help, I check my order history, there's no option to cancel the gift because it's already sent and they say they can't cancel the gift.

**G094** · `2420232` · first contact
  - **customer:** it also keeps saying on my party chat that 'party enchanted an error'

**G095** · `1757577` · follow-up
  - _customer_: Can’t use the search for a person function, is there a problem with it?
  - _brand_: Hi there, what happens when you try? Can you please DM: <URL> your gamertag and a detailed issue summary?
  - **customer:** Issue seemed to have fixed itself a little after I sent this. It just came up with gamer tag didn’t exist, even when I tried it with my friends gts. This was happening on the app and the console.

**G096** · `2975923` · first contact
  - **customer:** what is going on with Xbox one rn? Literally can't do anything, can't add ppl to party can't connect to any game my Internet is fine ps4 works wonderful like always. Xbox on other hand is being garbage as usual. Like maybe update your server status cause it's fucked

**G097** · `514978` · first contact
  - **customer:** wtf? I just want to come home after working all week to play my game and now I'm banned? Really? Way to ruin my experience, pls help. Like really?

**G098** · `2586836` · follow-up
  - _customer_: it's not letting me buy any games ? Keeps saying "purchase cannot be completed at this time please try again"
  - _customer_: Okay, also a game that was on sale 2 minutes ago suddenly isn't on sale anymore. What happened ? It was red dead redemption
  - _brand_: Sales can be limited time offers and we recommend staying up to date with offers here: <URL>
  - **customer:** It was literally only for 4 minutes on sale ??? I tried to buy when it was on sale but Xbox kept saying error

**G099** · `2782545` · first contact
  - **customer:** is it too late to get a refund of my digital deluxe edition of Call of Duty: WW2. The game is garbage and I can’t take it anymore.

**G100** · `515000` · first contact
  - **customer:** How's come Warhammer End Times: Vermintide game no work? Hard enough to convince my friends to play a free game u gave us, doesn't help when no one is able to get past the title screen without a server issue error message.

**G101** · `2896393` · first contact
  - _other_customer_: Yeerrrrpppp, i been trying to sign into my profile for two weeks now & y’all still won’t let me login. I done changed my password 7times & still nothing! wassup with that bro? @user
  - _customer_: Actually restore go to your settings, I had that same problem today
  - _other_customer_: bet. It’s not gone delete my games & apps is it?
  - **customer:** Nah you going to have an option that say keep game and apps

**G102** · `545519` · first contact
  - **customer:** so you get communication ban for calling someone a pussy?

**G103** · `170620` · first contact
  - **customer:** I payed a past due payment for xbox live and canceled the auto renewal xbox live subscription, now today it charged me again and it says it expires in less then a week???? i canceled auto renewal and want my money back!

**G104** · `858904` · first contact
  - **customer:** Ay @user @user Can Y'all Fix Upload Studio

**G105** · `522278` · first contact
  - **customer:** ‘Weeed UK’ Has now officially been deleted from my xbox.👋As Idk whether I need a new xbx but it randomly signs me out of the account whenever im in comp(only on that account)Therefore i cba it’s gone.

**G106** · `565151` · first contact
  - **customer:** Hi, my son has an xbox live account that was hacked Tuesday 28th November 2017. We have spoken to Microsoft every day since to resolve this issue to no avail. Please would you advise me as to how to proceed as we feel we are hitting a brick wall!!

**G107** · `101461` · first contact
  - _customer_: my xbox automatically turns on all the time, without me touching the powerswitch. sometimes I come home in the evening, and he is suddenly on. the xbox also makes sometimes a scraping sound. What can i do about it?
  - **customer:** did you recieve my message? I didnot get a reaction yet.

**G108** · `2874276` · first contact
  - **customer:** hey my friend @user is having issues with his Xbox

**G109** · `545544` · first contact
  - **customer:** Cant play one game without being kicked frm fucking xbx live fuck sake @user @user @user

**G110** · `2581231` · first contact
  - **customer:** why is my gamerpic I upload not showing as my gamerpic I use upload a custom image

**G111** · `661186` · first contact
  - **customer:** I have an Xbox One that will not turn on. I've turned it off and disconnected all the cables as well as the power supply. No response to turn on the Xbox and power supply has orange light. What can I do?

**G112** · `570275` · follow-up
  - _customer_: i am currently trying to download a game and it is getting "installation stopped" at 87 and 99 precent, i tried everything i could find online, what do i do please help!!!!
  - _customer_: thank your for getting back to me. it's on disc, it's an internal, yes it is plugged into a power strip
  - _brand_: Alrighty, let's unplug the power strip and plug the console directly into a wall outlet as the power strip can cause the console problems.
  - **customer:** the problem was fixed by your online support team

**G113** · `2849578` · first contact
  - **customer:** WTF. I have bought 10000 RUB prepaid cards an cant buy anything on xbox marketplace for 3 days. There appear a message when i want tobuy anything - you don't have enough money. And no one can help me.

**G114** · `2693439` · first contact
  - **customer:** I bought a game with some money I had left on a gift card and all it did was take my money and not give me anything can you help?

**G115** · `2682305` · first contact
  - **customer:** live down right now?

**G116** · `2903902` · follow-up
  - _customer_: how do I adjust Spotify volume when playing another game? I want to hear the game, but I also want to hear the music. Is there any way to turn the volume down for Spotify?
  - _customer_: This is while I’m listening to music <URL>
  - _brand_: Scroll all the way to the left to see if you see the song playing that you are listening to.
  - **customer:** All I see are my achievements, party, invites, friends, and Sign in

**G117** · `593795` · first contact
  - _customer_: My console keeps moving everything to the right side of every menu. Tried to restart, didn’t work. Fix? <URL>
  - **customer:** Found out it was a issue with the controller. Is it fixable?

**G118** · `493803` · first contact
  - **customer:** It won't let me do anything on my account without saying I need a security code for an email I don't have and because of that I can't change things till the 30th of December

**G119** · `183230` · first contact
  - **customer:** so my brother snapped my black ops 3 game disc in half when i literally own everything else on it digitally and can't buy just the fucking game now like WHY WOULD I REBUY A BUNDLE I HAVE dm me fuck

**G120** · `2707875` · first contact
  - **customer:** Watch out for this GamerTag. openmarrow28779. He invites people into private lobbies (GTAV) then hacks your accounts to gift games to himself. He's been reported and the 2 victims got a refund. @user @user

**G121** · `2636050` · first contact
  - **customer:** hi there. Im on Xbox One with internet connection, but it stucks when "connecting to Xbox live". I have tried following the troubleshooting from Microsoft, but with no luck.. I have only been able to get to matchmaking a few times. I get error 32770

**G122** · `2591633` · follow-up
  - _customer_: So I’m trying to share CoD ww2 with my Dad through this Network sharing thingy, and everytime he tries to download it, it will say Installation stopped.
  - _brand_: Hello, thanks for reaching out to us. Are you in the same household by chance?
  - **customer:** We are in the same household, on the same Wi-fi, on the same version of the Xbox One

**G123** · `573030` · first contact
  - **customer:** Is it possible to turn ( Instant-on ) mode on Xbox without a TV ?

**G124** · `2855552` · follow-up
  - _customer_: help me please I want to cancel ea access and I can't do it
  - _brand_: Hi there! What happens when you login here: <URL> and cancel the subscription?
  - **customer:** All good mate cheers for your help

**G125** · `2585946` · first contact
  - _customer_: explain these to me I can't even use my account <URL>
  - _other_customer_: You have been temp banned for violating the code of conduct. #xboxambassador
  - **customer:** The problem is I didn't do anything wrong

**G126** · `523165` · follow-up
  - _customer_: My Xbox just died 😢😭🤧😭
  - _brand_: Official Xbox Support here. Oh no. What exactly is going on with it? Could you tweet us more details, we'd love to help.
  - **customer:** I’m not sure why this happened. I downloaded the new call of duty and when finished my Xbox said it needed an update. When I turned it on the next day the only thing that pops up now is a colorful screen with lines.

**G127** · `1613671` · follow-up
  - _customer_: why do you hate white people? How is this name allowed but not my name regarding my Jewish heritage? I’m sending this to my local media outlet. <URL> imagine if my name targeted a specific race? This should never be allowed. “Crackas” are white people and targeting a race for violence is racism. Do you support racism?
  - _brand_: Hey there! Please report the user following the steps here: <URL> to report the user.
  - **customer:** Why don’t you just ban this name already? This is atrocious?l!

**G128** · `2796698` · first contact
  - **customer:** I downloaded Cities:Skyline when it was free on games with gold but now it's asking me to buy? How can this be resolved?

**G129** · `2795214` · first contact
  - **customer:** hey setting up the Xbox app with my new Xbox one x and I was wondering where to find this code help me out plz😌 <URL>

**G130** · `241134` · first contact
  - _brand_: We're back this morning and happy to help! If you didn't hear back from us overnight, send another tweet our way and we'll be happy to pick up where we left off :)
  - **customer:** Is the Xbox one media player going to be updated to play more 4K content from external hard drive. All I get is a green screen and sound

**G131** · `601589` · first contact
  - _customer_: I have a code for Fallout 3 that I got when buying Fallout 4 in Holland. I now live in Ireland and XBox Live won't let me download based on region/language. Can you help? I changed my region and language to NL to no avail.
  - **customer:** The XBox 360 had the most intuitive and brilliant UI. Chat, Party, everything. The XBox One is so bad it is infuriating. What happened?

**G132** · `2856902` · first contact
  - _brand_: Our Enforcement team works hard to keep Xbox Live safe & fun for everyone. Check out their site for details on the Xbox Live harassment policies: <URL>
  - _customer_: I got banned for telling a Frenchy to eat some slugs
  - **customer:** It was slugs lol called me a camping noobs for headglitching a bomb that I just planted 😂 then reported my response 2 week com ban and I'm sure they never respond to your appeal

**G133** · `449726` · first contact
  - **customer:** how can I transfer a download purchase from my Xbox 360 to new Xbox. Signed into the same gamer tag but asking me to pay again

**G134** · `40580` · first contact
  - **customer:** is there a reason why I can hear my White Xbox One S controller while it's on?

**G135** · `560712` · follow-up
  - _customer_: "forza horizon 3 xbox unable to join session" help i cant join mp
  - _customer_: <URL>
  - _brand_: Thanks for that! Looks as if your wireless strength is low. Let's try the steps here: <URL> to see if that helps.
  - **customer:** Dosent work still help

**G136** · `467213` · first contact
  - _brand_: The issues we were tracking with OneGuide on Xbox One should be resolved now. Give it another try and we’ll be here if you still need help!
  - **customer:** I must say, I’m very greatful for your support team and wish a lot of other companies cared about their customers like you guys do :)

**G137** · `542766` · first contact
  - **customer:** to @user, man I'm trying to play my games and it just tells me to try launch it again later the error code is (x80072f8f) please help

**G138** · `2911998` · first contact
  - **customer:** The right bumper on my day one edition Xbox one controller appears to be broken I’m going to scream

**G139** · `2455726` · first contact
  - **customer:** When playing split screen, my brother only shows up as a guest even though he's signed in. Is this intentional?

**G140** · `488317` · first contact
  - **customer:** Over 24 hours after my communications ban was lifted here we are, STILL ON COMMUNICATIONS BAN @user <URL>

**G141** · `519493` · first contact
  - **customer:** Just so you know I’m gonna @ you everyday multiple times a day until you get this shit straight @user @user

**G142** · `564242` · first contact
  - _brand_: Want to change things up a bit? Learn about Xbox One dashboard customization options with this handy video: <URL>
  - **customer:** Not having stupid Ali A on my dashboard would be an amazing start. Shame on you for plastering ads all over our home screen

**G143** · `2772850` · follow-up
  - _customer_: Ok so it says you guys can't help but um.. Is there anyway to find out what I did to get suspended and how long I'm suspended for? Feels weird to be suspended out of the blue 🤔 I haven't done anything different than what I have done in my 11 year tenure on XBL @user <URL> And when I go on the Enforcement page... It says I have a "perfect record" SO IM CONFUSED @user @user <URL>
  - _brand_: Hi there! We cannot speculate on enforcement actions here. You can find more information on your enforcement in your e-mail.
  - **customer:** Hey! I haven't received an email and yes I've checked my Spam folder Also can you double check if my account is in fact suspended and if so for how long? Maybe it's just a glitch because the enforcement page still says I have a perfect record. GT: bluffmaster007

**G144** · `558079` · first contact
  - **customer:** it's not letting me redeem my Xbox live code

**G145** · `2757877` · first contact
  - **customer:** just got off the phone with Xbox support....told me I can only play Xbox one if I have internet connection... even if I try to play online. Please my my internet bill then... or give me my money back for gold... #dontstealmymoney #notthe1sttime #reimbursement *offline

**G146** · `2511128` · first contact
  - **customer:** why is no one acknowledging the fact forza horizon 3 servers have now been down for 24 hours!!!! #help #girlracers

**G147** · `2910537` · first contact
  - _customer_: hey @user <URL>
  - _customer_: yes
  - _other_customer_: Go to settings, then down to preferences. Click on broadcast & capture, then click mic on
  - **customer:** i’ve done that

**G148** · `655963` · first contact
  - **customer:** hi I want to change the origin of my account as I keep getting the errors saying my account is not matching my location so I can't buy anything with my credit card... I changed my adresses but still email is from my native country. Pls help!

**G149** · `2654523` · first contact
  - **customer:** hy, after last update my controller on Xbox one x diaconnect from console with no reason

**G150** · `634657` · first contact
  - **customer:** I'm watching Datmowhawk get his Masters in Derpology. Come check it out here and lets make his day!: <URL> via @user

**G151** · `1757562` · follow-up
  - _customer_: I purchased 1 year subsricption to Xbox Gold and promotion said I would receive a free digital download code for Rainbow Six Siege. Still haven't received it and was wondering when or if I will? Promotion was right on my Xbox one's home screen. Would like to know cause I'd like this game asap and would be willing to spend $20 as it's on sale atm. But don't really want to if I get the free code.
  - _customer_: Yes I went through the promotion you see in the pic there and bought Gold through there and then that was it. I didn't get a confirmation or anything.
  - _brand_: Thanks for that clarification. We'd recommend continuing to keep an eye for this content to appear via your Xbox message center. If you do not receive this content by this time, feel free to reach back out to us.
  - **customer:** Okay thank you for your help, I figured would just take time but wanted to make sure. One more question. Would the code for the game only be redeemable on my account? Or could I send the code to a friend?

**G152** · `263026` · follow-up
  - _customer_: ayer me sucedió este bug estuvo "iniciando sesión " 5 horas, lo bueno es que me dejaba usarlo normal en los juegos y aplicaciones que tengo en marcas y favoritos. tuve que borrar el cache de la consola para que me dejara usar totalmente normal. <URL>
  - _brand_: Hi there! We're happy to help with any Xbox Support questions that you may have, but we're an English Support Channel. If you'd like to continue support in your native language, you can follow the link here: <URL>
  - **customer:** well this is the translation. this bug happened, he was "logging in" for 5 hours, all normal in the games and applications that I have in brands and favorites. I had to clear the console cache to let me use completely normal.

**G153** · `1693245` · first contact
  - **customer:** also when my mic is plugged in while im playing and charging it i cant hear people no more they can hear me but i cant hear them

**G154** · `2654489` · first contact
  - **customer:** The dragon ball super episode out. Fuck an Xbox

**G155** · `109422` · follow-up
  - _customer_: Brand new #XboxOneX #Scorpio @user @user is bricked after less than 20 hours of gaming. :/ Can't boot and fails to reset to factory settings even after 10-sec power cycle...
  - _brand_: Hey there, you can register your device here: <URL> and check for warranty and repair options. If you have any issues getting this done please reach out to our phone team here: <URL> for further assistance.
  - **customer:** I've created a repair order. .

**G156** · `705454` · first contact
  - **customer:** trying to do a live chat but saying it’s closed when does it open up Also how long does a review take to get a banned over turned I filed for a request , ,that’s is separate to why I want to talk to tw chat team

**G157** · `621222` · follow-up
  - _customer_: The audio quality in party chat is terrible for me even though I have set it up same as before on the one now I'm on the X. Everyone else is distorted.
  - _brand_: Hey there. This is something our teams are diving into after receiving some reports. Let us know if you see any change with this.
  - **customer:** Thank you for getting back to me, I will keep you up to date.

**G158** · `700164` · first contact
  - **customer:** tell me what this mean <URL>

**G159** · `176183` · first contact
  - **customer:** right Im still lagging on rocket league I'm having to uninstall then reinstall the game so I don't lag (temporary fix) this is really starting to p##s me off

**G160** · `169200` · follow-up
  - _customer_: does the xbox one x support AMD Freesync, because when i turn it on. I dont see a difference on framerate
  - _brand_: Hi there! That's not something we would be able to speculate on I am afraid. Are you seeing any error messages?
  - **customer:** No, but i dont see a difference. Freesync on on the #Xboxonex

**G161** · `454248` · first contact
  - **customer:** is oneguide down ? i've reset everything, Xbox detect usb tv tuner, but keep saying it cannot find tv provider whatever postal code I type :(

**G162** · `2654501` · first contact
  - **customer:** I really want this gamer tag but someone has it and they don’t even play anymore so if you can help I would be very thankful.

**G163** · `2420242` · first contact
  - **customer:** Hi, I just bought Minecraft for Xbox One to play with my friends, but I am unable to join them due to the fact they're playing a different version called 'Minecraft: Xbox One Edition', whereas my one is just 'Minecraft'? Is there any way for me to fix this?

**G164** · `466465` · first contact
  - **customer:** hello, I have issues with the Blu ray app. It happens with both the S and X. When you put a movie and choose Spanish as language to watch. It freezes.

**G165** · `516196` · first contact
  - **customer:** Hey @user still haven’t received my October game pass challenge reward.....

**G166** · `460972` · follow-up
  - _customer_: Hey @user, USB tv tuner suddenly stopped working today. Many reports on the forums stating the same thing, all starting today. What is going on?
  - _brand_: Hiya! The proper teams are hard at work on a fix. Please let us know if you see a change on your end.
  - **customer:** It seems to be working again, thanks for the quick fix.

**G167** · `592486` · first contact
  - **customer:** Hi. I want to block a game on my child's account that is not suitable for him and his ADHD. I do not want to block a range of games via age restrictions so how can I block just one specific game?

**G168** · `493809` · first contact
  - **customer:** Now that Sonic Adventure 2 is on Xbox One, when will the Battle DLC be on the console?

**G169** · `118386` · first contact
  - _brand_: Keep it simple and safe by setting up a passkey on your Xbox One profile: <URL>
  - **customer:** lmao yeah if my Xbox worked gg

**G170** · `456364` · first contact
  - **customer:** can someone tell me why this keeps happening anytime I put a disc in getting me right down now too the point I'm thinking of selling it and going too PlayStation <URL>

**G171** · `519464` · first contact
  - **customer:** Xbox✔️Destiny2✔️Clan✔️Go to play❌Fuckin Servers

**G172** · `918426` · first contact
  - **customer:** , just bought a new Xbox One X. Every game freaks out on me like this. Then it bleeds into my home screen. What’s happening?! #xboxonexproblems <URL>

**G173** · `118452` · first contact
  - **customer:** I accidentally bought Tom Clancy’s The Division when I actually wanted to buy Tom Clancy’s Rainbow Six Seige. Is their any possible way I could get a refund? My gamer tag is nuhxyz and I just bought the game last night

**G174** · `2867423` · first contact
  - **customer:** Any clue when keyboard and mouse support is coming to the Xbox One (X) ?

**G175** · `177198` · first contact
  - **customer:** hi, how would i go about fixing a banned payment instrument

**G176** · `2706407` · first contact
  - _brand_: Heya, let's start by power cycling your Xbox as outlined here: <URL> while the Xbox is off, power cycle your
  - **customer:** I fixed the issue

**G177** · `461017` · follow-up
  - _brand_: If you’re running into issues with OneGuide on Xbox One, proper teams are on the case.
  - _other_customer_: Hurry! I am missing the Redskins game. Derp.
  - _brand_: Hi there! If you bypass the console and go directly to the TV do you notice a change?
  - **customer:** Antenna works directly through tv , yes

**G178** · `2695210` · first contact
  - **customer:** My son's Xbox randomly powers itself on 2-3 times a day. Any idea what's causing this?

**G179** · `2785454` · first contact
  - **customer:** I can't purchase any items for my avatar

**G180** · `170572` · follow-up
  - _brand_: No, your Xbox One is not haunted, check out our guide here if it keeps turning off by itself: <URL>
  - _other_customer_: Once I got my S when it first released I starting plugging them directly into the wall. So my day 1, S and Project Scorpio are all plugged into the wall.
  - _brand_: Gotcha. Are you noticing any performance issues with the console? Were you able to test resetting the power supply?
  - **customer:** Ive actually had the same issue for a long time. It’s plugged directly into a wall outlet

**G181** · `2866233` · follow-up
  - _customer_: I'm trying to scan my QR code with my Kinect but the Xbox one doesn't give me that option
  - _brand_: Hi there. I'm afraid that feature has been removed from the Xbox One Kinect Sensor. If you'd like to See this feature return, be sure to let us know via the link here <URL>
  - **customer:** Hopefully it comes back. Games still give us QR codes. Also adding it to the app helps too. <URL>

**G182** · `509897` · first contact
  - **customer:** I have a game downloaded onto my hardrive and It doesn’t let me play the game it makes me go to the store any fix?

**G183** · `558076` · first contact
  - **customer:** hi I don’t use my Xbox anymore and I was charged for a new year, was wondering if I could get a refund?

**G184** · `570250` · first contact
  - **customer:** Are you kidding me, i have spent thousands with Microsoft and they could give a shit @user

**G185** · `2966722` · first contact
  - _customer_: Does anyone elses #XboxOneX sound like this? @user <URL>
  - _customer_: It is, I'll give that a go and report back. Here's a video from cold boot to on, and then back to energy saving mode. <URL>
  - _other_customer_: Pretty sure it’s the HDD bearing failing. Soon the bearing will seize and the console will not boot. Not a Microsoft issue necessarily. Bummer but it’s awesome to see @user is so responsive. I’ve had many Ps4pro issues and never got that level of service. Best of luck!
  - **customer:** I think you could be onto something there with the HDD! And yes the customer service so far has been great :)

**G186** · `2380148` · first contact
  - **customer:** i redeemed an xbox live gold code this morning however am still unable to use any gold features such as parties and other online features. Under my account subscriptions it says i am subscribed yet im still not able to use the features. Just wondering how i can fix? <URL>

**G187** · `2916138` · first contact
  - **customer:** i cant access my settings or anything on the main menu, i know i have a gold membership but idk if my GT got hacked

**G188** · `2629352` · follow-up
  - _customer_: My new Xbox One X isn’t finding my WiFi network anymore?! Still works on all other devices!
  - _brand_: Hey there! Let's follow the guide here: <URL> for more help with this!
  - **customer:** Yeah I tried all them this morning before I left for work, none worked. Wireless was working fine till yesterday evening

**G189** · `2955643` · first contact
  - **customer:** what is taking so long for my Xbox Design Lab controller to ship?? I placed my order on 11/10 and have already been charged. No one via phone has been able to provide an answer for this lengthy delay

**G190** · `2667877` · first contact
  - **customer:** Will anyone who spent money on Marvel Heroes Omega be getting refunds after the shutdown? Its not been out that long.

**G191** · `2799590` · first contact
  - **customer:** why is my xbox giving me serives are down messages when i start playing a game when i just got off a game and it was working just fine

**G192** · `552410` · first contact
  - _customer_: Please can you do GTA San Andreas Xbox One Backwards Compatibility?
  - _other_customer_: Hello, you can vote for games to be backwards compatible here: <URL> #XboxHelp
  - **customer:** I've been voted it :)

**G193** · `863740` · first contact
  - **customer:** espn app is garbage on Xbox one. Keeps buffering.

**G194** · `1327675` · first contact
  - **customer:** Nice one, @user @user @user #XboxOneX #fail <URL>

**G195** · `863734` · first contact
  - **customer:** new scorpio edition wont fully boot. Tried chat support and MS store for fixes. If I request device repair via MS site am I definitely getting a scorpio edition back or is it possible I'd get a regular one x. #fanboy

**G196** · `2926577` · first contact
  - **customer:** Is anyone experienced with using the Xbox Elite controller on PC? Can't configure the controller at all in app. Help? @user

**G197** · `2856893` · first contact
  - _customer_: so my scorpio freeze all the time and now shows the code E 105 00000000 8006045D .. can i do something against it without repair? factory settings doesn‘t work
  - **customer:** Now we have E102 10040C02 80004005.. strange

**G198** · `62014` · first contact
  - _customer_: Xbox Overheated Twice In The Past 4 Minutes. @user
  - _other_customer_: that’s happened to me before just like go outside for a hour or two and come back and it should be fine. and move it away from things near it like walls, games, etc.
  - **customer:** It's on top of my desk my TV is like 6 inches away from it besides that there is nothing around it

**G199** · `121828` · first contact
  - **customer:** When will the xbox one x launch in India ? Or should I just go ahead and buy a PS4 Pro 😜😆😆

**G200** · `2916143` · first contact
  - **customer:** Kind of gutted that I bought @user @user origins @user then my Xbox power supply died 💔
