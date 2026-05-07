# NagarSetu

NagarSetu is a Flask and SQLite civic issue reporting app with citizen and municipal admin workflows.

Tagline: **Your Bridge to Better Cities**

## Features

- Email registration and login with password hashing
- Citizen and admin roles
- Citizen issue reporting with description, manual location, category, and before image upload
- Leaflet/OpenStreetMap location picker with latitude/longitude capture
- Reverse geocoding to auto-fill the address after selecting a map point
- Nearby complaint detection within 1 km to reduce duplicate reports
- Community repost/support system with one repost per citizen per complaint
- Smart duplicate detection using distance, category, and description keyword similarity
- Public Community Map page with category, status, priority, area search, and distance filters
- Map popup cards with complaint status, images, verifications, repost counts, and support actions
- Expanded complaint categories with an "Others" custom category field
- Public issue board with filters for status and escalated complaints
- Community verification with duplicate prevention and verified badges after 5 verifications
- Community priority levels: Low, Medium, High, Critical
- Automatic escalation indicators: Warning after 2 days and Escalated after 5 days
- Admin dashboard with complaint totals, map view, escalation alerts, most verified/reposted complaints, repeated issue detection, and area hotspot statistics
- Admin status updates: Pending, In Progress, Resolved
- Multiple after-resolution image uploads and before/after comparison
- Image preview modal for complaint photos
- CSRF protection for form submissions
- Responsive orange-themed UI

## Run

```powershell
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000/`.

The app uses CDN-hosted Leaflet assets and OpenStreetMap/Nominatim services in the browser for map tiles and reverse geocoding, so map features need internet access from the browser.

## Test Accounts Created During Verification

- Citizen: `citizen@example.com` / `password123`
- Admin: `admin@example.com` / `password123`

You can also register new Citizen or Admin accounts from the login page.

## Project Structure

```text
app.py
requirements.txt
templates/
static/
  css/styles.css
  js/main.js
  uploads/
civicsetu.db
```
