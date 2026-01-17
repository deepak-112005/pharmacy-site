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
    address = db.Column(db.String(500)) 
    phone = db.Column(db.String(20))

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
    status = db.Column(db.String(20)) 

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
    if not MedicalRegistry.query.filter_by(license_number="REG-12345").first():
        db.session.add(MedicalRegistry(license_number="REG-12345", doctor_name="Dr. Arun", expiry_date=datetime.now().date()+timedelta(days=365), status="Active"))
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

@app.route('/api/suggestions')
def get_suggestions():
    q = request.args.get('q', '').lower()
    if len(q) < 2: return jsonify([])
    results = Product.query.filter((Product.name.ilike(f'%{q}%')) | (Product.search_tags.ilike(f'%{q}%'))).limit(5).all()
    return jsonify([{"id": p.id, "name": p.name, "cat": p.category.name} for p in results])

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.address = request.form.get('address')
        current_user.phone = request.form.get('phone')
        db.session.commit()
        flash('Profile updated successfully!', 'success')
    order_count = Order.query.filter_by(user_id=current_user.id).count()
    return render_template('profile.html', user=current_user, order_count=order_count)

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
        flash("Invalid Credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/cart')
def cart():
    cart_ids = session.get('cart', [])
    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    return render_template('cart.html', products=products, total=sum(p.price for p in products))

@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    session.setdefault('cart', [])
    if product_id not in session['cart']:
        session['cart'].append(product_id)
        session.modified = True
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_ids = session.get('cart', [])
    if not cart_ids: return redirect(url_for('index'))
    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    total = sum(p.price for p in products)
     # Medicine names-ah string-ah mathuroam
    med_names = ", ".join([p.name for p in products])
    if request.method == 'POST':
        file = request.files.get('prescription')
        filename = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        order = Order(user_id=current_user.id, full_name=request.form['name'], address=request.form['address'], 
                      phone=request.form['phone'], prescription_file=filename, payment_method=request.form['payment'],
                      total_amount=total, verification_status="Approved")
        db.session.add(order); db.session.commit(); session.pop('cart', None)
        flash("Order placed successfully!", "success")
        return redirect(url_for('my_orders'))
    return render_template('checkout.html', products=products, total=total)

@app.route('/my_orders')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.id).all()
    return render_template('orders.html', orders=orders)

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.username != 'admin': return redirect(url_for('index'))
    # Statistics
    p_count = Product.query.count()
    o_count = Order.query.count()
    total_rev = db.session.query(db.func.sum(Order.total_amount)).scalar() or 0
    # Category Data for Charts
    med_count = Product.query.join(Category).filter(Category.name == 'MEDICINES').count()
    cos_count = Product.query.join(Category).filter(Category.name == 'COSMETICS & PERSONAL CARE').count()
    inst_count = Product.query.join(Category).filter(Category.name == 'MEDICAL INSTRUMENTS').count()
    
    return render_template('admin.html', 
                           products=Product.query.all(), orders=Order.query.all(),
                           categories=Category.query.all(), p_count=p_count, o_count=o_count, 
                           total_rev=total_rev, med_count=med_count, 
                           cos_count=cos_count, inst_count=inst_count)

# Advanced: Order Categories
    pending_orders = Order.query.filter_by(verification_status='Pending').all()
    verified_orders = Order.query.filter_by(verification_status='Approved').all()
    
    # Advanced: User Management
    users = User.query.filter(User.username != 'admin').all()
    
    products = Product.query.all()
    categories = Category.query.all()
    
    return render_template('admin.html', 
                           p_count=p_count, o_count=o_count, 
                           total_rev=total_rev, products=products, 
                           pending_orders=pending_orders, verified_orders=verified_orders,
                           users=users, categories=categories)

@app.route('/download_invoice/<int:order_id>')
@login_required
def download_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, "INVOICE - Medi kart", ln=True, align='C')
    pdf.set_font("Arial", '', 12); pdf.cell(190, 10, f"Customer: {order.full_name} | Total: Rs.{order.total_amount}", ln=True)
    res = make_response(pdf.output(dest='S').encode('latin-1'))
    res.headers['Content-Disposition'] = f'attachment; filename=invoice_{order.id}.pdf'
    res.headers['Content-Type'] = 'application/pdf'
    return res

# --- Cancel Order Route ---
@app.route('/cancel_order/<int:id>')
@login_required
def cancel_order(id):
    order = Order.query.get(id)
    if order and order.user_id == current_user.id:
        db.session.delete(order)
        db.session.commit()
        flash("Order cancelled successfully!", "info")
    return redirect(url_for('my_orders'))

@app.route('/admin/update_status/<int:order_id>/<string:status>')
@login_required
def update_order_status(order_id, status):
    # Admin check
    if current_user.username != 'admin':
        return redirect(url_for('index'))
    
    order = Order.query.get_or_404(order_id)
    order.verification_status = status  # Inga 'Packing' illa 'Delivered' nu mathuroam
    db.session.commit()
    
    flash(f"Order #MK-{order_id} status updated to {status}!", "success")
    return redirect(url_for('admin_dashboard'))    

# --- KADAISI-LA THAAN ITHU IRUKANUM ---
if __name__ == '__main__':
    app.run(debug=True)