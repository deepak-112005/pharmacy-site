from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF 
from PIL import Image
from datetime import datetime
from flask_mail import Mail, Message
import random
import os

# 1. INITIALIZE APP
app = Flask(__name__)
app.secret_key = "pharmacy_secret_key"

# 2. CONFIGURATIONS
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'pharmacy.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email Config
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

# 5. HELPERS
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_order_email(order, user):
    try:
        msg = Message(f"Medi kart: Order Confirmed #MK-{order.id}", 
                      sender=app.config['MAIL_USERNAME'], recipients=[user.email])
        msg.body = f"Hi {user.username},\n\nOrder Confirmed!\nTotal: ₹{order.total_amount}\nMedicines: {order.medicines_ordered}\nDelivery to: {order.address}\n\nTrack here: http://127.0.0.1:5000/track/{order.id}"
        mail.send(msg)
    except Exception as e:
        print(f"Email Error: {e}")

def send_otp_email(email, otp):
    try:
        msg = Message('Medi kart: Your OTP Verification Code', 
                      sender=app.config['MAIL_USERNAME'], recipients=[email])
        msg.body = f"Your verification code is: {otp}. Valid for 5 minutes."
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Mail Error: {e}")
        return False

# 6. ROUTES
@app.route('/')
def index():
    categories = Category.query.all()
    q = request.args.get('q', '').strip()
    cat_id = request.args.get('cat')
    if cat_id: products = Product.query.filter_by(category_id=cat_id).all()
    elif q: products = Product.query.filter((Product.name.contains(q)) | (Product.search_tags.contains(q))).all()
    else: products = Product.query.all()
    return render_template('index.html', products=products, categories=categories)

@app.route('/cart')
def cart():
    cart_session = session.get('cart', {})
    if isinstance(cart_session, list): # Fix for old list-based cart
        new_cart = {}
        for p_id in cart_session: new_cart[str(p_id)] = new_cart.get(str(p_id), 0) + 1
        session['cart'] = new_cart
        cart_session = new_cart

    products_in_cart = []
    subtotal = 0
    for p_id, qty in cart_session.items():
        product = db.session.get(Product, int(p_id))
        if product:
            item_total = product.price * qty
            subtotal += item_total
            products_in_cart.append({'info': product, 'qty': qty, 'total': item_total})
    
    delivery = 40 if subtotal < 500 and subtotal > 0 else 0
    return render_template('cart.html', items=products_in_cart, subtotal=subtotal, delivery=delivery, total=subtotal + delivery)

@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    cart = session.get('cart', {})
    if not isinstance(cart, dict): cart = {}
    cart[str(product_id)] = cart.get(str(product_id), 0) + 1
    session['cart'] = cart
    session.modified = True
    flash("Added to cart!", "success")
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_dict = session.get('cart', {})
    if not cart_dict: return redirect(url_for('index'))

    products = Product.query.filter(Product.id.in_(cart_dict.keys())).all()
    total = sum(p.price * cart_dict.get(str(p.id), 1) for p in products)

    if request.method == 'POST':
        file = request.files.get('prescription')
        filename = None
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        # Capture medicine names for DB
        med_names = ", ".join([p.name for p in products])

        new_order = Order(
            user_id=current_user.id, 
            full_name=request.form.get('name'), 
            address=request.form.get('address'), 
            phone=request.form.get('phone'), 
            prescription_file=filename, 
            payment_method=request.form.get('payment'),
            total_amount=total, 
            medicines_ordered=med_names,
            verification_status="Approved"
        )
        db.session.add(new_order)
        db.session.commit()

        send_order_email(new_order, current_user)
        session.pop('cart', None)
        flash("Order Placed Successfully!", "success")
        return redirect(url_for('my_orders'))

    return render_template('checkout.html', products=products, total=total)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.phone = request.form.get('phone')
        current_user.address = request.form.get('address')
        db.session.commit()
        flash('Profile updated!', 'success')
    order_count = Order.query.filter_by(user_id=current_user.id).count()
    return render_template('profile.html', user=current_user, order_count=order_count)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uemail = request.form.get('email')
        if User.query.filter_by(email=uemail).first():
            flash("Email already exists!", "danger")
            return redirect(url_for('register'))

        otp_code = str(random.randint(100000, 999999))
        new_user = User(
            username=request.form.get('username'), 
            email=uemail, 
            phone=request.form.get('phone'),
            password=generate_password_hash(request.form.get('password')),
            lat=request.form.get('lat'), lng=request.form.get('lng'), 
            otp=otp_code
        )
        db.session.add(new_user)
        db.session.commit()
        
        send_otp_email(uemail, otp_code)
        session['verify_user_id'] = new_user.id
        flash("Check email for OTP!", "info")
        return redirect(url_for('verify_otp'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            otp_code = str(random.randint(100000, 999999))
            user.otp = otp_code
            db.session.commit()
            send_otp_email(user.email, otp_code)
            session['verify_user_id'] = user.id
            return redirect(url_for('verify_otp'))
        flash('Invalid Credentials', 'danger')
    return render_template('login.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    user_id = session.get('verify_user_id')
    if not user_id: return redirect(url_for('login'))
    user = db.session.get(User, user_id)

    if request.method == 'POST':
        if request.form.get('otp') == user.otp:
            user.is_active = True
            db.session.commit()
            login_user(user)
            session.pop('verify_user_id', None)
            return redirect(url_for('index'))
        flash('Invalid OTP', 'danger')
    return render_template('verify_otp.html')

@app.route('/my_orders')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('orders.html', orders=orders)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))



# 1. CANCEL ORDER ROUTE
@app.route('/cancel_order/<int:id>')
@login_required
def cancel_order(id):
    order = db.session.get(Order, id)
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for('my_orders'))
    
    # Security: Order panna user mattum thaan cancel panna mudiyum
    if order.user_id == current_user.id or current_user.username == 'admin':
        db.session.delete(order)
        db.session.commit()
        flash('Order has been cancelled successfully.', 'info')
    else:
        flash('Unauthorized action!', 'danger')
    return redirect(url_for('my_orders'))

# 2. DOWNLOAD INVOICE ROUTE
@app.route('/download_invoice/<int:order_id>')
@login_required
def download_invoice(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for('my_orders'))
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, "INVOICE - Medi kart", ln=True, align='C')
    res = make_response(pdf.output(dest='S').encode('latin-1'))
    res.headers['Content-Disposition'] = f'attachment; filename=invoice_{order.id}.pdf'
    res.headers['Content-Type'] = 'application/pdf'
    return res

# 3. TRACK ORDER ROUTE
@app.route('/track/<int:order_id>')
@login_required
def track_order(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for('my_orders'))
    
    # Coordinates (Chennai example)
    pharmacy_coords = [13.0827, 80.2707] 
    user_lat = float(current_user.lat) if current_user.lat else 13.0475
    user_lng = float(current_user.lng) if current_user.lng else 80.2090
    user_coords = [user_lat, user_lng]
    
    return render_template('track.html', order=order, pharmacy=pharmacy_coords, user=user_coords)
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)