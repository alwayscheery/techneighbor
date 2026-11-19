# TechNeighbor

A Python/Django consumer app helping older adults book companionship, everyday help, and technology support through one community center. Arc Testnet provides portable volunteer service credentials. ElevenLabs powers a guided listening path through booking.

## Hackathon submission hosting

Live judging demo: **https://techneighbor-hackathon.onrender.com/**. It runs on free Render hosting with persistent Neon PostgreSQL storage and works while the developer’s Mac is off. The free web service sleeps after inactivity; allow about a minute for the first visit to wake it. See [HOSTING.md](HOSTING.md) for setup and how to stop the demo after judging.

## Run locally

Python 3.12 or newer:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py setup_demo
python manage.py setup_community
python manage.py setup_neighbors
python manage.py runserver 127.0.0.1:8000
```

On macOS, `Start TechNeighbor.command` performs setup and starts the local server. The first dependency installation can take several minutes. Open http://127.0.0.1:8000/ . Coordinator sign-in details are generated in `LOCAL_ACCESS.txt`; keep that file private. Repeating setup preserves the account and adds future slots. Reset a forgotten password with `python manage.py changepassword coordinator`.

## Product features

- Three categories and nine activities: companionship (chat, gentle walk, board game), everyday help (errand planning, small-task organization, everyday letters), and technology help (video calls, phone basics, photos).
- Session booking, printing, cancellation, coordinator completion, and status/category filters. Database constraints prevent double-booking across categories.
- Nearby-neighbor directory with area/interest filters, Google Maps links, opt-in reviewed profiles, and private coordinator introductions.
- Community hub with activities, private attendance lists, seat reservations, and coordinator notices.
- Shared community photo albums with coordinator approval, accessible descriptions, owner removal, and reporting.
- Light/dark mode, remembered text sizes from 90% to 200%, keyboard controls, text labels, visible focus, reduced-motion support, and written equivalents of every spoken instruction.
- A dedicated **Book with spoken guidance** path with ElevenLabs audio, pause/replay, slower playback, and instructions for choosing support, time, details, review, and next steps. It does not submit a booking automatically.
- Staff-only issuance of volunteer service credentials for completed sessions; public verification, proof JSON export, revocation, and explorer links.

All sessions start at the fictional community center. This prototype does not arrange home visits, deliveries, transportation, personal care, volunteer matching, or real messages.

## Nearby neighbors and Google Maps

Open `/neighbors/` to choose a supported general area and shared interest. **Open Google Maps** opens that city or neighborhood in Google Maps; **Find a public meeting place** searches nearby libraries and community centers. These use the official [Google Maps URLs API](https://developers.google.com/maps/documentation/urls/get-started), which requires no API key. The app does not ask for device location, calculate exact distances, or collect home addresses. The bundled 2025 U.S. Census place catalog covers 32,058 cities and communities across all 50 states and Washington, D.C. Choose a state, type a city, and select a matching area. Search returns at most 40 choices at once; the entire catalog is never put in a dropdown. Search also works without JavaScript using the form buttons. It runs locally without Google geocoding calls. Census places do not include every informal neighborhood; coordinators can still add a missing general area. See `booking/data/README.md` for provenance and coverage.

Residents can opt into a public profile at `/neighbors/profile/`. Nickname, selected area, interest, and introduction remain private until a coordinator approves the listing. Editing requires a new review. The same browser session controls edits and withdrawal. Clearing cookies loses these controls; coordinator assistance is then needed. Withdrawal or coordinator hiding closes pending introduction requests involving that profile. Profile review does not verify identity or background.

An approved resident can ask for an introduction to another approved resident. Their contact details and note are visible only to themselves and the coordinator, never in the public directory, Google Maps, ElevenLabs, or onchain. Requests are deduplicated and limited to three per requester per day. No email, text, or meeting is sent/booked automatically: the coordinator must obtain both people's agreement and arrange a public venue. Sample profiles are clearly fictional and cannot receive requests.

Coordinators review profiles and introduction requests at `/coordinator/neighbors/`. Choose **Phone demo** to review the separate phone database. `python manage.py setup_neighbors` imports the national catalog and seeds four clearly fictional profiles without overwriting real profiles. `python manage.py import_us_areas` imports only the place catalog; repeat imports preserve existing area IDs and profile links. Run migrations and that command for each database profile.

An optional interactive in-app map is implemented but is **not connected or live-tested with a Google key**. Maps links are the working default. To enable the interactive map later, use `/coordinator/neighbors/maps/` or environment variables `GOOGLE_MAPS_API_KEY` and `GOOGLE_MAPS_MAP_ID`. Enable Maps JavaScript API and billing in Google Cloud, restrict the browser key to exact website domains and Maps JavaScript API, and configure usage limits/billing alerts. See [Google’s official setup instructions](https://developers.google.com/maps/documentation/javascript/get-api-key). The saved key is outside Git in `.private/maps.json`; browser keys are necessarily visible to map visitors and must be restricted. `DEMO_MAP_ID` is used for testing unless a production map ID is configured.

The Google script loads only after **Load Google map** is selected. Markers show broad area centers and counts, never individual homes or names. Profiles remain available if the map fails. The Maps provider may charge for interactive map loads; no Google billing account or key was created for this feature.

## Expanded ElevenLabs experience

**Spoken lessons** (`/learn/`) offers three narrated mini-lessons: making a video call, sharing a photo, and spotting suspicious messages. Each has a visible transcript, explicit Listen/replay, native pause controls, and normal or slower playback. Community activity pages, the hub, albums, and photo uploads also provide spoken instructions. The guide appears before the upload form. Nothing on these new pages starts speaking automatically.

Fifteen fixed clips are generated through the ElevenLabs text-to-speech API using `eleven_multilingual_v2` and privately cached: the original eight booking clips, four community guides, and three lessons. No arbitrary user text, photo descriptions, images, attendee names, or captions are sent to the provider. These guides explain how to use the page; they do not narrate changing activity details or individual uploaded photographs.

After connecting a key, run `python manage.py prepare_voice` to prepare all clips, or pass fixed keys such as `python manage.py prepare_voice community upload lesson_calls`. Cached clips are reused. The public demo remains cache-only, so visitors cannot trigger new provider charges. All seven new clips were generated with the real ElevenLabs connection; lesson playback and slower speed were verified in the browser. A fresh source copy excludes the private cache and must prepare its own audio.

## Community hub and photo albums

Open `/community/` for activities and notices, `/community/albums/` for shared albums, or `/community/photos/upload/` to upload. `setup_community` creates three empty albums and clearly labelled fictional activities; repeating it is safe. Activity reservations use the browser session and do not publish attendee names.

Uploads accept JPEG, PNG, or WebP up to 8 MB and 24 million pixels. A description for people using screen readers and permission to share are required. Images are decoded, resized to at most 2,000 pixels per side, stripped of metadata, and converted to JPEG before storage. Pending images are visible only to their uploader in the same browser session and to a signed-in coordinator. Approved images are publicly shared; albums are not restricted to community members. Uploaders can remove their own images and visitors can report concerns. Clearing browser cookies loses uploader controls.

Coordinators approve, hide, and review reports at `/coordinator/community/`. To review uploads from the separate phone demo, choose **Phone demo** or open `http://127.0.0.1:8000/coordinator/community/?source=phone` on this Mac. Public coordinator routes remain blocked. The local app accesses the phone database directly without copying private bookings.

Normalized image bytes are stored in the database and served through permission-checked views, so pending files have no public media directory. Photos and captions never go onchain or to ElevenLabs. Keep database backups; source exports deliberately exclude uploads. A permanent deployment must preserve the database and configure production storage and abuse controls before real community use.

## Arc Testnet integration

Chain ID: `5042002`. RPC: `https://rpc.testnet.arc.io`.

Public demonstration registry: `0x0787438357a9A46AA2560f3f019c0677b5a2C8a8`.
Issuer: `0xb311D3e025270af9e6c3C78BCAB230BEe98B7321`.
Deployment transaction: `0x351ae09f873652cf00b88a9f5df3d5573016fc0f878d37f9759e9120a30eaf6f`.
Explorer: https://explorer.testnet.arc.io/address/0x0787438357a9A46AA2560f3f019c0677b5a2C8a8

Source, ABI, bytecode, compiler settings and deployment metadata are in `contracts/`. The contract uses Solidity 0.8.30, optimization with 200 runs, and the Paris EVM target. Runtime bytecode is checked before contract use. Onchain fields are only a random credential ID, volunteer wallet, issue time, and revocation time; the registry itself identifies the issuer. No resident names, contact details, booking links, session topics or hashes of private session data are encoded.

Coordinators mark a session completed, select **Issue service credential**, enter the volunteer's public EVM wallet, and confirm completion and consent. The signing key stays in `.private/arc.json`; the backend signs zero-value, testnet-only transactions. Issuance and revocation permissions are enforced by the contract. One credential is linked to each completed booking. A saved raw transaction can be replayed on a retry without issuing a second credential. Failed or unconfirmed writes never become verified credentials.

The verification page reads the contract at a specific current block, compares the deployed code and issuer/recipient, and shows current revocation status. An RPC outage produces **Could not verify right now**, never a cached verified badge. A pending revocation is identified as pending. Public proof JSON contains only blockchain identifiers; resident and volunteer aliases remain private.

### Fresh installation

Open `/coordinator/integrations/`, create a dedicated organization test wallet, fund its address with free Arc Testnet USDC from https://faucet.circle.com/ , then select **Check and deploy**. The included deployed registry is public, but its signing key is intentionally excluded from the source archive. A fresh copy must create its own issuer to issue new credentials. No real-money funding is needed.

### Independent verification without the app database

```sh
python manage.py verify_credential 0xCREDENTIAL_ID --contract 0xREGISTRY_ADDRESS
```

Use the full 32-byte credential ID from the proof JSON. This reads the public network directly; it does not look up a booking or use the organization's private key. `contracts/sample-proof.json` is a real, fictional-data test example from the public deployment.

The registry proves that the displayed issuer made a statement. It does not independently prove that help occurred, vet a volunteer, or establish a real-world organization's identity. Our issuer is explicitly a fictional demonstration organization. Revocation cannot remove the historical public record. A volunteer wallet can be pseudonymous; do not publish someone else's wallet without their agreement.

## ElevenLabs integration

Open `/coordinator/integrations/` and save an ElevenLabs API key with Text to Speech access. The default voice is `JBFqnCBsd6RMkjVDRZzb` (George); choose a voice your account can use. `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` environment variables are also supported. Keys entered through the form are stored in `.private/elevenlabs.json`, never rendered back into HTML. The backend calls the real ElevenLabs Text to Speech API using `eleven_multilingual_v2` and MP3 output.

Only allowlisted, fixed guide text is sent to ElevenLabs. Resident names, contacts, selected appointment details and microphone recordings are not sent. There is no microphone feature. The same transcript appears on screen. Guide audio is requested only after a person starts listening (or deliberately follows the spoken booking path), and the guide can be stopped. An active guide continues between category and confirmation pages in that browser session. Generation results are cached privately; the endpoint is CSRF-protected and has a per-session request limit.

There is no substitute audio provider. Without a valid key, sufficient credits and voice access, the app clearly says speech is unavailable and keeps the written flow working. Key setup alone is not evidence of a working bounty demo: test actual provider audio and include it in the submission video. API requests may consume the connected account's credits.

## Adjustable text size

The display toolbar includes Make text smaller, Make text bigger, and Reset controls. Available sizes are 90%, 100%, 125%, 150%, 175% and 200%. Reset restores 100%. Preferences are saved in browser local storage and applied before rendering; controls still work on the current page if storage is blocked. Screen readers receive size-change announcements, and controls support native keyboard activation. Text uses relative units; enlarged forms and support cards reflow on narrow screens. Phone-width homepage and booking-form checks at 200% found no horizontal overflow. Browser zoom remains available.

## Architecture

Browser → Django templates/forms/views → SQLite for private booking data.
Coordinator confirmation → `booking/blockchain.py` → signed Arc Testnet registry call.
Public verifier → Arc RPC → runtime, issuer, recipient and revocation checks at a named block.
Spoken-guide UI → CSRF-protected Django endpoint → allowlisted ElevenLabs TTS request → audio playback with transcript.

`booking/integrations.py` handles private local settings and serializes signer access. `.private/` contains test keys, signed transaction recovery data, and audio caches; exclude it from every public export. Resident booking UUID links are private capability links that allow viewing and cancellation. Volunteer proof URLs are separately generated and safe to share because they omit private booking identifiers.

## Verification

```sh
python -m pip install -r requirements-dev.txt
python manage.py check
python manage.py test
```

The 94 passing tests include upload validation, metadata removal, pending-photo privacy, approval, removal, reports, CSRF, reservation capacity, and cross-database phone moderation. Neighbor tests cover profile consent/privacy, approval and withdrawal, area/interest filtering, private and deduplicated introductions, request limits, Google URL encoding, Maps key setup permissions, and phone-demo route restrictions. Catalog tests cover all 50 states/DC, import repeatability, legacy profile preservation, repeated city names, city selection in profiles, and bounded nationwide search responses. The tests also execute real compiled Solidity bytecode in a local PyEVM Ethereum test engine and cover issuer permissions, duplicate IDs, revocation, privacy, public verification, outages, CSRF and the ElevenLabs API request shape. Local EVM tests are not a replacement for testing Arc-specific runtime differences. Public Arc Testnet issuance and revocation were also exercised against the deployment above. Provider request tests use a mock ElevenLabs response. Separately, all 15 guide and lesson clips were generated through the actual ElevenLabs API, and browser playback plus slower reading speed were verified with the configured account. The local demonstration key is restricted to Text to Speech, capped at 3,000 credits per refresh period, and expires November 22, 2026. The key itself is excluded from exports.

To rebuild the artifact, install Node.js and `solc@0.8.30`, then run `node contracts/compile.cjs`. Recompilation is not required to run the app. Keep `ServiceCredentials.sol` and its compiled JSON together.

## Hackathon scope

Main track: Consumer Applications. Chain award target: Best use of Arc. Bounty target: ElevenLabs. The README documents the core onchain functionality and contract address; the spoken guide must be demonstrated with real ElevenLabs audio before claiming the voice integration is working in a submission. Final eligibility and awards are decided by the organizers/judges. The early booking prototype was created before kickoff; confirm reuse rules with organizers. New integration work does not by itself resolve those rules.

Before real public use, configure a production server, HTTPS, DEBUG=False, approved hosts, secure cookies, key management, access controls, stronger abuse limits, backups, privacy/retention policies and an actual organization's volunteer approval process. The bundled server is for local demonstration only.

## Temporary phone demonstration

`techneighbor.settings_phone` runs an isolated demonstration database in `.private/phone-demo.sqlite3` with DEBUG disabled, secure cookies, an explicit host allowlist, and no coordinator accounts. `setup_phone_demo` seeds fictional sessions and public sample-credential metadata only. An allowlist middleware blocks coordinator, admin, issuance, revocation, and unknown routes; all requests are anonymous. Voice playback is cache-only in this mode and cannot generate new provider charges.

The current temporary HTTPS address is saved in the sibling `PHONE_LINK.md`. It is provided through a Cloudflare Quick Tunnel to a separate local listener on port 8001. The Mac and both processes must remain running. This is a testing link, not permanent hosting; a new tunnel gets a new hostname.

To configure this profile, set `TECHNEIGHBOR_PHONE_HOST` to the exact tunnel hostname, run migrations, `setup_phone_demo`, and `setup_community` with `--settings=techneighbor.settings_phone`, and start a separate local demo server on port 8001. For the temporary demo, the development server uses `--insecure` only to serve the bundled static assets while DEBUG is off; the public tunnel provides HTTPS. Do not tunnel the private coordinator server on port 8000. Use proper hosting, a production server and static-file configuration for a lasting deployment.


## Community fund and volunteer rewards (Arc Testnet only)

Open `/community/fund/` for the current fund balance, distributed test USDC, reward count and public receipts. Residents keep using ordinary free bookings without a wallet. Coordinators mark a session completed, choose **Approve volunteer reward**, confirm the volunteer’s agreed public address, then choose **Send test reward** on the receipt.

`CommunityFund.sol` pays a fixed **2 native test USDC** per random receipt ID, once per ID, to a nonzero address. Only its separately configured reward operator can pay. The contract limits rewards to ten per UTC day; its initial funding is 10 test USDC. Native Arc USDC uses 18 decimals for contract value. Resident names, contact details, session topics, booking links and volunteer aliases never go onchain. The coordinator still determines whether service was completed; blockchain records prove the payment, not service quality.

The new reward-only operator key is separate from the existing credential-issuer key. Render uses the private `ARC_REWARD_PRIVATE_KEY` environment setting. The existing organization/credential key remains local. There is no public signing endpoint, and approvals/payments require staff login, CSRF protection and POST. The fixed amount and recipient cannot be changed after approval. One session has one reward record. The exact signed transaction is persisted before broadcast; retries reuse it, and an unresolved earlier payment blocks signing a new one to avoid nonce collisions after a crash.

The public fund totals are read at one current block with runtime-bytecode/operator/owner checks. A network outage shows unavailable status, never an invented successful payment. Each receipt checks the current contract record. A saved database status alone is not proof. Real Arc Testnet deployment, funding, payment and duplicate retry were verified; public identifiers are in `contracts/reward-deployment.json` and `contracts/sample-reward.json`. Only this deliberately fictional reward example is seeded on the hosted demo.

For a new installation, the private local command `python manage.py setup_reward_fund` deploys and funds a new contract using an already-funded Arc Testnet organization wallet. It saves a separate reward operator key under `.private/rewards.json`; source exports exclude it. It is safe to repeat saved deployment/funding transactions. `node contracts/compile.cjs` rebuilds both contracts with solc 0.8.30, optimizer 200 runs and Paris EVM. No real tokens or charitable donations are involved. Remove the Render reward-key environment setting to disable new hosted payments.

Voice uses ElevenLabs internally; provider branding is omitted from the website’s visible copy at the project owner’s request. Provider details remain documented here for judges.
