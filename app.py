from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF 
from PIL import Image
from datetime import datetime, timedelta
import easyocr
import re
import os

# ---------------- APP CONFIG ----------------
app = Flask(__name__)
app.secret_key = "pharmacy_secret_key"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'pharmacy.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ---------------- EXTENSIONS ----------------
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# ---------------- HELPERS ----------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------------- MODELS ----------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    # Puthu columns for Profile
    address = db.Column(db.String(500)) 
    phone = db.Column(db.String(20))

# --- Profile Route ---
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        # User update pandra details-ah save pandrom
        current_user.address = request.form.get('address')
        current_user.phone = request.form.get('phone')
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))
        
    # User panna orders count edukkurom summary-kaga
    order_count = Order.query.filter_by(user_id=current_user.id).count()
    return render_template('profile.html', user=current_user, order_count=order_count)
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    products = db.relationship('Product', backref='category', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(50), unique=True)
    name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    stock_quantity = db.Column(db.Integer, default=50)
    image_url = db.Column(db.String(200))
    search_tags = db.Column(db.String(200))

class MedicalRegistry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    license_number = db.Column(db.String(50), unique=True)
    doctor_name = db.Column(db.String(100))
    expiry_date = db.Column(db.Date)
    status = db.Column(db.String(20)) # 'Active' or 'Suspended'

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    full_name = db.Column(db.String(100))
    address = db.Column(db.String(500))
    phone = db.Column(db.String(20))
    prescription_file = db.Column(db.String(200))
    payment_method = db.Column(db.String(50))
    total_amount = db.Column(db.Float)
    verification_status = db.Column(db.String(50), default='Pending')
    flag_reason = db.Column(db.String(200))
    doctor_license_detected = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
REAL_PRODUCTS = [
    # (Inga thaan neenga anupuna antha full list-ah paste pannanum)
    {"sku": "MED-001", "name": "Dolo 650 Tablet", "price": 30.0, "cat": "MEDICINES", "tags": "fever, pain relief, paracetamol, headache", "desc": "Used for fever and mild to moderate pain."},
    # ... baki ulla ellathaiyum inga paste pannunga ...
]
def seed_database():
    # 1. Categories-ah create pandrom
    categories = [
        "MEDICINES", "COSMETICS & PERSONAL CARE", "MEDICAL INSTRUMENTS",
        "SURGICAL & FIRST AID ITEMS", "HOSPITAL HYGIENE PRODUCTS",
        "WELLNESS & HEALTH SUPPLEMENTS", "OTHERS"
    ]
    
    cat_map = {}
    for c_name in categories:
        cat = Category.query.filter_by(name=c_name).first()
        if not cat:
            cat = Category(name=c_name)
            db.session.add(cat)
            db.session.commit()
        cat_map[c_name] = cat.id

    # 2. Products-ah SKU check panni add pandrom
    for p in REAL_PRODUCTS:
        existing = Product.query.filter_by(sku=p['sku']).first()
        if not existing:
            new_item = Product(
                sku=p['sku'],
                name=p['name'],
                price=p['price'],
                category_id=cat_map[p['cat']],
                description=p['desc'],
                stock_quantity=50,
                search_tags=p['tags'],
                image_url="https://via.placeholder.com/150"
            )
            db.session.add(new_item)
    db.session.commit()
# ---------------- OCR AI LOGIC ----------------
def verify_prescription_ai(file_path):
    try:
        reader = easyocr.Reader(['en'])
        result = reader.readtext(file_path, detail=0)
        text = " ".join(result).upper()
        
        match = re.search(r'REG-\d{5}', text)
        if not match:
            return "Flagged", "License Number not found", "Unknown"
        
        doc_license = match.group()
        doctor = MedicalRegistry.query.filter_by(license_number=doc_license).first()
        
        if not doctor:
            return "Blocked", "Doctor not in Registry", doc_license
        if doctor.status == 'Suspended':
            return "Blocked", "Doctor Suspended", doc_license
        if doctor.expiry_date < datetime.now().date():
            return "Flagged", "License Expired", doc_license

        return "Approved", "Verified by EasyOCR", doc_license
    except Exception as e:
        return "Error", str(e), "Error"

# ---------------- SEED DATA ----------------
# --- 1. REAL_PRODUCTS LIST (Function-ku veliya irukanum) ---
REAL_PRODUCTS = [
    # MEDICINES
    {"sku": "MED-001", "name": "Dolo 650 Tablet", "price": 30.0, "cat": "MEDICINES", "tags": "fever, paracetamol", "desc": "Relieves fever and body pain."},
    {"sku": "MED-002", "name": "Limcee Vitamin C", "price": 25.0, "cat": "MEDICINES", "tags": "vitamin, immunity", "desc": "Vitamin C chewable tablets."},
    {"sku": "MED-003", "name": "Saridon", "price": 40.0, "cat": "MEDICINES", "tags": "headache", "desc": "Fast relief from headache."},
    {"sku": "MED-004", "name": "Digene Gel (Mint)", "price": 150.0, "cat": "MEDICINES", "tags": "acidity, gas", "desc": "Antacid for gas and acidity."},
    {"sku": "MED-005", "name": "Vicks Vaporub", "price": 95.0, "cat": "MEDICINES", "tags": "cold, cough", "desc": "Relief from nose congestion."},
    {"sku": "MED-006", "name": "Avil 25mg", "price": 15.0, "cat": "MEDICINES", "tags": "allergy", "desc": "Anti-allergic medicine."},

    # COSMETICS
    {"sku": "COS-001", "name": "Vaseline Body Lotion", "price": 280.0, "cat": "COSMETICS & PERSONAL CARE", "tags": "skin, moisturizer", "desc": "Deep moisture for dry skin."},
    {"sku": "COS-002", "name": "Himalaya Face Wash", "price": 110.0, "cat": "COSMETICS & PERSONAL CARE", "tags": "face, acne", "desc": "Purifying Neem face wash."},
    {"sku": "COS-003", "name": "Ponds Dreamflower", "price": 180.0, "cat": "COSMETICS & PERSONAL CARE", "tags": "powder, skin", "desc": "Fragrant talcum powder."},
    {"sku": "COS-004", "name": "Biotique Sunscreen", "price": 450.0, "cat": "COSMETICS & PERSONAL CARE", "tags": "sun, uv protection", "desc": "Bio Sandalwood SPF 50+."},

    # INSTRUMENTS
    {"sku": "INST-001", "name": "Pulse Oximeter", "price": 1200.0, "cat": "MEDICAL INSTRUMENTS", "tags": "oxygen, heart rate", "desc": "Digital fingertip pulse oximeter."},
    {"sku": "INST-002", "name": "Digital Thermometer", "price": 240.0, "cat": "MEDICAL INSTRUMENTS", "tags": "fever, temperature", "desc": "High precision digital sensor."},
    {"sku": "INST-003", "name": "Glucometer Kit", "price": 950.0, "cat": "MEDICAL INSTRUMENTS", "tags": "sugar, diabetes", "desc": "Blood glucose monitoring system."},
    {"sku": "INST-004", "name": "Steamer Inhaler", "price": 350.0, "cat": "MEDICAL INSTRUMENTS", "tags": "cold, steam", "desc": "Facial steamer and inhaler."},

    # SURGICAL
    {"sku": "SURG-001", "name": "Dettol Antiseptic", "price": 190.0, "cat": "SURGICAL & FIRST AID ITEMS", "tags": "wounds, germs", "desc": "Disinfectant liquid."},
    {"sku": "SURG-002", "name": "Crepe Bandage", "price": 220.0, "cat": "SURGICAL & FIRST AID ITEMS", "tags": "sprain, pain", "desc": "Elastic bandage for muscle pain."},
    {"sku": "SURG-003", "name": "Savlon Liquid", "price": 85.0, "cat": "SURGICAL & FIRST AID ITEMS", "tags": "antiseptic", "desc": "Wound cleaning liquid."},
    {"sku": "SURG-004", "name": "Cotton Roll 500g", "price": 250.0, "cat": "SURGICAL & FIRST AID ITEMS", "tags": "surgical cotton", "desc": "Pure absorbent sterile cotton."},

    # HYGIENE
    {"sku": "HYG-001", "name": "Hand Sanitizer 500ml", "price": 240.0, "cat": "HOSPITAL HYGIENE PRODUCTS", "tags": "alcohol, gems", "desc": "70% alcohol based sanitizer."},
    {"sku": "HYG-002", "name": "Disposable Masks (50)", "price": 150.0, "cat": "HOSPITAL HYGIENE PRODUCTS", "tags": "mask, surgical", "desc": "3-Ply surgical face masks."},

    # WELLNESS
    {"sku": "WELL-001", "name": "Horlicks Women's Plus", "price": 340.0, "cat": "WELLNESS & HEALTH SUPPLEMENTS", "tags": "bone health, woman", "desc": "Health drink for bone strength."},
    {"sku": "WELL-002", "name": "Chyawanprash (1kg)", "price": 450.0, "cat": "WELLNESS & HEALTH SUPPLEMENTS", "tags": "immunity, herbal", "desc": "Dabur Ayurvedic immunity booster."},

    # OTHERS
    {"sku": "OTHR-001", "name": "Electric Hot Bag", "price": 350.0, "cat": "OTHERS", "tags": "heat therapy, pain", "desc": "Rechargeable heat water bag."},
    {"sku": "OTHR-002", "name": "Back Support Belt", "price": 850.0, "cat": "OTHERS", "tags": "back pain, support", "desc": "Lumbar support for back pain."}
]

# --- 2. SEED DATABASE FUNCTION ---
def seed_database():
    categories_list = [
        "MEDICINES", "COSMETICS & PERSONAL CARE", "MEDICAL INSTRUMENTS",
        "SURGICAL & FIRST AID ITEMS", "HOSPITAL HYGIENE PRODUCTS",
        "WELLNESS & HEALTH SUPPLEMENTS", "OTHERS"
    ]
    
    cat_map = {}
    for c_name in categories_list:
        cat = Category.query.filter_by(name=c_name).first()
        if not cat:
            cat = Category(name=c_name)
            db.session.add(cat)
            db.session.commit()
        cat_map[c_name] = cat.id

    # Sync Products
    for item in REAL_PRODUCTS:
        if not Product.query.filter_by(sku=item['sku']).first():
            db.session.add(Product(
                sku=item['sku'], 
                name=item['name'], 
                price=item['price'], 
                category_id=cat_map[item['cat']], 
                description=item['desc'],
                search_tags=item['tags'], 
                image_url="https://via.placeholder.com/150"
            ))
    
    # Sync Medical Registry
    if not MedicalRegistry.query.filter_by(license_number="REG-12345").first():
        db.session.add(MedicalRegistry(
            license_number="REG-12345", 
            doctor_name="Dr. Arun", 
            expiry_date=datetime.now().date()+timedelta(days=365), 
            status="Active"
        ))
    
    db.session.commit()

# --- 3. EXECUTION ---
with app.app_context():
    db.create_all()
    seed_database() # Mismatch fix: seed_database-ah call pandrom
    print("Database is ready with real-world products!")


# ---------------- ROUTES ----------------
@app.route('/')
def index():
    # 1. Ella categories-aiyum sidebar-kaga edukkurom
    categories = Category.query.all()
    
    # 2. Search query matrum Category filter check pandrom
    q = request.args.get('q', '').strip()
    cat_id = request.args.get('cat')

    if cat_id:
        # Particular category click panna products filter aagum
        products = Product.query.filter_by(category_id=cat_id).all()
    elif q:
        products = Product.query.filter(
            (Product.name.contains(q)) | (Product.search_tags.contains(q))
        ).all()
    else:
        products = Product.query.all()
        
    return render_template('index.html', products=products, categories=categories)
app.route('/api/suggestions')
def get_suggestions():
    q = request.args.get('q', '').lower()
    if len(q) < 2: return jsonify([])
    results = Product.query.filter((Product.name.ilike(f'%{q}%')) | (Product.search_tags.ilike(f'%{q}%'))).limit(5).all()
    return jsonify([{"id": p.id, "name": p.name, "cat": p.category.name} for p in results])

@app.route('/ai_assistant', methods=['POST'])
def ai_assistant():
    user_input = request.form.get('symptom', '').lower()
    suggestions = []
    if "fever" in user_input: suggestions = Product.query.filter(Product.name.ilike('%Dolo%')).all()
    elif "breathing" in user_input: suggestions = Product.query.filter(Product.name.ilike('%Nebulizer%')).all()
    return render_template('index.html', products=Product.query.all(), suggestions=suggestions, query=user_input)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname, email, pwd = request.form['username'], request.form['email'], request.form['password']
        if not User.query.filter((User.username == uname) | (User.email == email)).first():
            db.session.add(User(username=uname, email=email, password=generate_password_hash(pwd)))
            db.session.commit()
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('index'))

@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    session.setdefault('cart', [])
    session['cart'].append(product_id); session.modified = True
    return redirect(url_for('index'))

@app.route('/cart')
def cart():
    cart_ids = session.get('cart', [])
    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    return render_template('cart.html', products=products, total=sum(p.price for p in products))

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_ids = session.get('cart', [])
    if not cart_ids: return redirect(url_for('index'))
    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    total = sum(p.price for p in products)

    if request.method == 'POST':
        file = request.files.get('prescription')
        filename, status, reason, doc_lic = None, "Pending", "No Prescription", "N/A"
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            status, reason, doc_lic = verify_prescription_ai(path)

        order = Order(user_id=current_user.id, full_name=request.form['name'], address=request.form['address'], 
                      phone=request.form['phone'], prescription_file=filename, payment_method=request.form['payment'],
                      total_amount=total, verification_status=status, flag_reason=reason, doctor_license_detected=doc_lic)
        db.session.add(order); db.session.commit(); session.pop('cart', None)
        flash(f"Order Placed! AI Status: {status}", "success")
        return redirect(url_for('my_orders'))
    return render_template('checkout.html', products=products, total=total)

@app.route('/my_orders')
@login_required
def my_orders():
    return render_template('orders.html', orders=Order.query.filter_by(user_id=current_user.id).all())

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.username != 'admin':
        return redirect(url_for('index'))
    
    # Dashboard-kaga chinna calculations
    p_count = Product.query.count()
    o_count = Order.query.count()
    total_rev = db.session.query(db.func.sum(Order.total_amount)).scalar() or 0
    
    products = Product.query.all()
    orders = Order.query.all()
    categories = Category.query.all()
    
    return render_template('admin.html', 
                           p_count=p_count, o_count=o_count, 
                           total_rev=total_rev, products=products, 
                           orders=orders, categories=categories)
@app.route('/download_invoice/<int:order_id>')
@login_required
def download_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, "INVOICE - Medi kart", ln=True, align='C')
    pdf.set_font("Arial", '', 12); pdf.cell(190, 10, f"Customer: {order.full_name} | Total: Rs.{order.total_amount}", ln=True)
    res = make_response(pdf.output(dest='S').encode('latin-1'))
    res.headers['Content-Disposition'] = f'attachment; filename=invoice_{order.id}.pdf'
    res.headers['Content-Type'] = 'application/pdf'; return res

if __name__ == '__main__':
    app.run(debug=True)