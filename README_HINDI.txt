SARASWATI VIDYA MANDIR PUBLIC SCHOOL, SEMLA
Website + Admin Panel (Python Flask + SQLite) — Updated Project

SAFE UPDATE / DATA PRESERVATION
- This is an update of the existing Flask project, not a rebuild.
- New tables are added to school.db when the app starts. Existing tables and records are not dropped.
- This ZIP is a separate copy. Extract it into a NEW folder; do not extract over your original project.
- If you already have a school.db from an earlier running copy, copy that database into this extracted project folder BEFORE starting it. Back up school.db first. The app keeps existing records and adds the new feature tables.
- Uploaded photos live in static/uploads. Back up this folder too.

WINDOWS STARTUP
1. Install Python 3.10+ from python.org and tick "Add Python to PATH".
2. Right-click the ZIP > Extract All. Keep the original ZIP/project unchanged.
3. Open the extracted Saraswati_School_Website folder.
4. Double-click run_windows.bat. First launch needs internet to install Flask.
5. Open http://127.0.0.1:5000 in your browser. Keep the black terminal window open while using the site.
6. Stop the server by pressing Ctrl+C in the terminal.

ADMIN LOGIN
URL: http://127.0.0.1:5000/admin/login
Username: admin
Password: Admin@12345
Change the password immediately after login from Admin Panel > Change Password.

NEW FEATURES
- Student management with automatically generated IDs such as SVM-00001.
- Student and fee payment records stored in SQLite database school.db.
- Monthly fee payments and balance calculations.
- April 2025–March 2026 academic-year monthly fee card.
- Fee receipts with print and WhatsApp pre-filled message links.
- Manual WhatsApp fee reminders; messages are never sent automatically.
- Admin-controlled photo gallery shown on the public homepage.
- School van/vehicle and driver/route management.
- Dashboard summary including students, collected fees and vans.
- Responsive, colorful English admin interface.

FEE NOTES
- Add each student and their monthly fee before recording payments.
- Fee month uses YYYY-MM format; the card covers April 2025 to March 2026.
- Outstanding balances on the card are calculated for that academic year only. Payments are attributed to the selected fee month.
- WhatsApp needs a valid phone number with country code (for India, usually 91 followed by the 10-digit mobile number). The browser opens a prepared message; an admin must review and send it.
- Receipts are generated for individual recorded payments.

SECURITY
- Change the default admin password.
- Before public deployment, set a strong random SCHOOL_SECRET_KEY, use HTTPS, turn debug off and use a production WSGI server.
- Student and parent data is private; protect the laptop and make regular backups.

EXISTING FEATURES RETAINED
Homepage, school details, teachers/staff, notices, admission enquiries, admin login and password change remain in the project.
