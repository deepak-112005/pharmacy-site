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
import random 
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
    phone = db.Column(db.String(20), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500)) 
    
    # Auto-Location & OTP Info
    country = db.Column(db.String(100))
    state = db.Column(db.String(100))
    city = db.Column(db.String(100))
    lat = db.Column(db.String(50))
    lng = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=False) 
    otp = db.Column(db.String(6))
    otp_expiry = db.Column(db.DateTime)
    reg_date = db.Column(db.DateTime, default=datetime.utcnow)

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
    doctor_license_detected = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- SEED DATA ----------------
REAL_PRODUCTS = [
    {"sku": "MED-001", "name": "Dolo 650 Tablet", "price": 30.0, "cat": "MEDICINES", "tags": "fever, paracetamol", "desc": "Relieves fever."},
    {"sku": "MED-002", "name": "Limcee Vitamin C", "price": 25.0, "cat": "MEDICINES", "tags": "vitamin, immunity", "desc": "Vitamin C tablets."},
    {"sku": "COS-001", "name": "Himalaya Face Wash", "price": 110.0, "cat": "COSMETICS & PERSONAL CARE", "tags": "face, acne", "desc": "Neem face wash."},
    {"sku": "INST-001", "name": "Pulse Oximeter", "price": 1200.0, "cat": "MEDICAL INSTRUMENTS", "tags": "oxygen, heart rate", "desc": "Digital pulse oximeter."}
]

def seed_database():
    categories_list = ["MEDICINES", "COSMETICS & PERSONAL CARE", "MEDICAL INSTRUMENTS", "SURGICAL & FIRST AID ITEMS", "HOSPITAL HYGIENE PRODUCTS", "WELLNESS & HEALTH SUPPLEMENTS", "OTHERS"]
    cat_map = {}
    for c_name in categories_list:
        cat = Category.query.filter_by(name=c_name).first() or Category(name=c_name)
        db.session.add(cat); db.session.commit()
        cat_map[c_name] = cat.id
    for item in REAL_PRODUCTS:
        if not Product.query.filter_by(sku=item['sku']).first():
            db.session.add(Product(sku=item['sku'], name=item['name'], price=item['price'], category_id=cat_map[item['cat']], description=item['desc'], search_tags=item['tags'], image_url="https://via.placeholder.com/150"))
    db.session.commit()

with app.app_context():
    db.create_all()
    seed_database()

# ---------------- ROUTES ----------------

@app.route('/')
def index():
    categories = Category.query.all()
    q = request.args.get('q', '').strip()
    cat_id = request.args.get('cat')
    if cat_id: products = Product.query.filter_by(category_id=cat_id).all()
    elif q: products = Product.query.filter((Product.name.contains(q)) | (Product.search_tags.contains(q))).all()
    else: products = Product.query.all()
    return render_template('index.html', products=products, categories=categories)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname, uemail, uphone, pwd = request.form.get('username'), request.form.get('email'), request.form.get('phone'), request.form.get('password')
        lat, lng = request.form.get('lat'), request.form.get('lng')
        
        if not all([uname, uemail, uphone, pwd]):
            flash("All fields are required!", "danger")
            return redirect(url_for('register'))

        if User.query.filter((User.username == uname) | (User.email == uemail)).first():
            flash("User already exists!", "danger")
            return redirect(url_for('register'))

        otp_code = str(random.randint(100000, 999999))
        new_user = User(
            username=uname, email=uemail, phone=uphone,
            password=generate_password_hash(pwd),
            lat=lat, lng=lng, otp=otp_code,
            otp_expiry=datetime.now() + timedelta(minutes=5)
        )
        db.session.add(new_user); db.session.commit()
        
        print(f"DEBUG: OTP for {uemail} is {otp_code}") # Inga OTP terminal-la thiriyum
        session['verify_user_id'] = new_user.id
        flash("OTP generated! Please verify to activate account.", "info")
        return redirect(url_for('verify_otp'))
    return render_template('register.html')

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    user_id = session.get('verify_user_id')
    if not user_id: return redirect(url_for('register'))
    user = User.query.get(user_id)
    if request.method == 'POST':
        if user.otp == request.form.get('otp') and datetime.now() < user.otp_expiry:
            user.is_active = True
            db.session.commit()
            flash("Account Verified!", "success")
            return redirect(url_for('login'))
        flash("Invalid OTP!", "danger")
    return render_template('verify_otp.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            if not user.is_active and user.username != 'admin':
                flash("Account not verified! Check OTP.", "warning")
                return redirect(url_for('verify_otp'))
            login_user(user)
            return redirect(url_for('index'))
        flash("Invalid Credentials", "danger")
    return render_template('login.html')

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.phone = request.form.get('phone')
        current_user.address = request.form.get('address')
        db.session.commit()
        flash('Updated!', 'success')
    return render_template('profile.html', order_count=Order.query.filter_by(user_id=current_user.id).count())

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.username != 'admin': return redirect(url_for('index'))
    
    # Stats
    total_rev = db.session.query(db.func.sum(Order.total_amount)).scalar() or 0
    low_stock = Product.query.filter(Product.stock_quantity < 10).count()
    
    # Chart Data
    med_count = Product.query.join(Category).filter(Category.name == 'MEDICINES').count()
    cos_count = Product.query.join(Category).filter(Category.name == 'COSMETICS & PERSONAL CARE').count()
    inst_count = Product.query.join(Category).filter(Category.name == 'MEDICAL INSTRUMENTS').count()

    return render_template('admin.html', 
        p_count=Product.query.count(), o_count=Order.query.count(),
        total_rev=total_rev, products=Product.query.all(), 
        users=User.query.filter(User.username != 'admin').all(),
        categories=Category.query.all(), low_stock_count=low_stock,
        med_count=med_count, cos_count=cos_count, inst_count=inst_count
    )

@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    session.setdefault('cart', [])
    if product_id not in session['cart']:
        session['cart'].append(product_id); session.modified = True
    return redirect(url_for('cart'))

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
        order = Order(
            user_id=current_user.id, full_name=request.form['name'],
            address=request.form['address'], phone=request.form['phone'],
            total_amount=total
        )
        db.session.add(order); db.session.commit()
        session.pop('cart', None)
        flash("Order Placed!", "success")
        return redirect(url_for('my_orders'))
    return render_template('checkout.html', products=products, total=total)

@app.route('/my_orders')
@login_required
def my_orders():
    return render_template('orders.html', orders=Order.query.filter_by(user_id=current_user.id).all())

@app.route('/logout')
def logout():
    logout_user(); return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)