from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF 
from PIL import Image
from datetime import datetime, timedelta
from flask_mail import Mail, Message
import easyocr
import random
import re
import os

# 1. INITIALIZE APP
app = Flask(__name__)
app.secret_key = "pharmacy_secret_key"

# 2. CONFIGURATIONS
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'pharmacy.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email Config (Only Email now)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'deepaksdpi05@gmail.com' 
app.config['MAIL_PASSWORD'] = 'fsqdmediftdhsyip'    
mail = Mail(app)

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 3. EXTENSIONS
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# 4. MODELS
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500)) 
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
    payment_method = db.Column(db.String(50))
    total_amount = db.Column(db.Float)
    medicines_ordered = db.Column(db.String(500)) 
    status = db.Column(db.String(50), default='Processing')
    prescription_file = db.Column(db.String(200))
    verification_status = db.Column(db.String(50), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# 5. HELPERS (Email Only)
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_notifications(order, user):
    msg_body = f"Hi {user.username},\n\nOrder #MK-{order.id} confirmed!\nTotal: ₹{order.total_amount}\nDelivery Address: {order.address}\n\nGet well soon! - Medi kart"
    try:
        msg = Message(f"Medi kart: Order Confirmed #MK-{order.id}", sender=app.config['MAIL_USERNAME'], recipients=[user.email])
        msg.body = msg_body
        mail.send(msg)
    except Exception as e: print(f"Email Notification Error: {e}")

def send_otp_email(email, otp):
    try:
        msg = Message('Medi kart: Your OTP Verification Code', 
                      sender=app.config['MAIL_USERNAME'], 
                      recipients=[email])
        msg.body = f"Your verification code is: {otp}. It will expire in 5 minutes."
        mail.send(msg)
        return True
    except Exception as e:
        print(f"OTP Mail Error: {e}")
        return False

# 6. SEED DATA
def seed_database():
    categories_list = ["MEDICINES", "COSMETICS & PERSONAL CARE", "MEDICAL INSTRUMENTS", "SURGICAL & FIRST AID ITEMS", "WELLNESS & HEALTH SUPPLEMENTS"]
    for c_name in categories_list:
        if not Category.query.filter_by(name=c_name).first():
            db.session.add(Category(name=c_name))
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
        if User.query.filter((User.username == uname) | (User.email == uemail)).first():
            flash("User already exists!", "danger"); return redirect(url_for('register'))

        otp_code = str(random.randint(100000, 999999))
        new_user = User(username=uname, email=uemail, phone=uphone, password=generate_password_hash(pwd), otp=otp_code)
        db.session.add(new_user); db.session.commit()
        
        send_otp_email(uemail, otp_code)
        session['verify_user_id'] = new_user.id
        flash("OTP sent to your email for account activation!", "info")
        return redirect(url_for('verify_otp'))
    return render_template('register.html')

@app.route('/profile')
@login_required
def profile():
    # User-oda orders count-ah edukrom
    order_count = Order.query.filter_by(user_id=current_user.id).count()
    return render_template('profile.html', user=current_user, order_count=order_count)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    # Profile update logic
    current_user.phone = request.form.get('phone')
    current_user.address = request.form.get('address')
    db.session.commit()
    flash('Account updated successfully!', 'success')
    return redirect(url_for('profile'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            otp_code = str(random.randint(100000, 999999))
            user.otp = otp_code
            db.session.commit()
            
            print(f"DEBUG: Login OTP for {user.username} is {otp_code}")
            send_otp_email(user.email, otp_code)
            
            session['verify_user_id'] = user.id
            flash("Login OTP sent to your email!", "info")
            return redirect(url_for('verify_otp'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    user_id = session.get('verify_user_id')
    if not user_id: return redirect(url_for('login'))
    user = db.session.get(User, user_id)

    if request.method == 'POST':
        user_otp = request.form.get('otp').strip()
        db_otp = str(user.otp).strip() if user.otp else ""

        if user_otp == db_otp:
            user.is_active = True
            user.otp = None 
            db.session.commit()
            login_user(user)
            session.pop('verify_user_id', None)
            flash('Successfully Verified!', 'success')
            return redirect(url_for('index'))
        flash('Invalid OTP code! Try again.', 'danger')
    return render_template('verify_otp.html')

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_ids = session.get('cart', [])
    if not cart_ids: return redirect(url_for('index'))
    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    total = sum(p.price for p in products)

    if request.method == 'POST':
        file = request.files.get('prescription')
        filename = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        new_order = Order(
            user_id=current_user.id, full_name=request.form.get('name'), 
            address=request.form.get('address'), phone=request.form.get('phone'), 
            prescription_file=filename, payment_method=request.form.get('payment'),
            total_amount=total, medicines_ordered=", ".join([p.name for p in products])
        )
        db.session.add(new_order); db.session.commit()
        send_notifications(new_order, current_user)
        session.pop('cart', None)
        flash("Order Placed Successfully!", "success")
        return redirect(url_for('my_orders'))
    return render_template('checkout.html', products=products, total=total)

@app.route('/logout')
@login_required
def logout():
    logout_user(); session.clear()
    flash("Logged out.", "info")
    return redirect(url_for('index'))

# --- OTHER ROUTES ---
@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    if 'cart' not in session:
        session['cart'] = {} # Dictionary: {product_id: quantity}
    
    cart = session['cart']
    p_id = str(product_id)
    
    if p_id in cart:
        cart[p_id] += 1
    else:
        cart[p_id] = 1
    
    session.modified = True
    flash("Product added to cart!", "success")
    return redirect(url_for('cart'))

@app.route('/update_cart/<int:product_id>/<action>')
def update_cart(product_id, action):
    cart = session.get('cart', {})
    p_id = str(product_id)
    
    if p_id in cart:
        if action == 'add':
            cart[p_id] += 1
        elif action == 'sub' and cart[p_id] > 1:
            cart[p_id] -= 1
        elif action == 'remove':
            cart.pop(p_id)
            
    session.modified = True
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    cart_items = session.get('cart', {})
    products_in_cart = []
    subtotal = 0
    
    for p_id, qty in cart_items.items():
        product = db.session.get(Product, int(p_id))
        if product:
            item_total = product.price * qty
            subtotal += item_total
            products_in_cart.append({
                'info': product,
                'qty': qty,
                'total': item_total
            })
    
    delivery = 40 if subtotal < 500 and subtotal > 0 else 0
    grand_total = subtotal + delivery
    
    return render_template('cart.html', items=products_in_cart, subtotal=subtotal, delivery=delivery, total=grand_total)



@app.route('/my_orders')
@login_required
def my_orders():
    return render_template('orders.html', orders=Order.query.filter_by(user_id=current_user.id).all())

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.username != 'admin': return redirect(url_for('index'))
    return render_template('admin.html', 
        p_count=Product.query.count(), o_count=Order.query.count(),
        total_rev=db.session.query(db.func.sum(Order.total_amount)).scalar() or 0,
        products=Product.query.all(), users=User.query.filter(User.username != 'admin').all(),
        categories=Category.query.all()
    )

if __name__ == '__main__':
    app.run(debug=True)