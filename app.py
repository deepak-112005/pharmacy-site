from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF 
from datetime import datetime
from flask_mail import Mail, Message
import random
import os
import sqlite3

# 1. INITIALIZE APP
app = Flask(__name__)
app.secret_key = "pharmacy_secret_key"
def add_role_column():
    conn = sqlite3.connect('pharmacy.db')
    cursor = conn.cursor()
    try:
        cursor.execute('ALTER TABLE user ADD COLUMN role VARCHAR(10) DEFAULT "user"')
        conn.commit()
        print("Role column added successfully!")
    except sqlite3.OperationalError:
        print("Role column already exists.")
    conn.close()
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
    role = db.Column(db.String(10), default='user') # 'admin' or 'user'
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
    verification_status = db.Column(db.String(50), default='Pending') # Default logic changed to Pending
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
        msg.body = f"Hi {user.username},\n\nOrder Confirmed!\nTotal: ₹{order.total_amount}\n\nTrack here: http://127.0.0.1:5000/track/{order.id}"
        mail.send(msg)
    except Exception as e: print(f"Email Error: {e}")

def send_otp_email(email, otp):
    try:
        msg = Message('Medi kart: OTP Code', sender=app.config['MAIL_USERNAME'], recipients=[email])
        msg.body = f"Your verification code is: {otp}"
        mail.send(msg)
        return True
    except Exception as e: return False

# 6. USER ROUTES
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
    if 'cart' not in session or not isinstance(session['cart'], dict): session['cart'] = {}
    cart = session['cart']
    p_id = str(product_id)
    cart[p_id] = cart.get(p_id, 0) + 1
    session.modified = True
    return jsonify({"success": True, "cart_count": sum(cart.values())})

@app.route('/update_cart/<int:product_id>/<string:action>')
def update_cart(product_id, action):
    cart = session.get('cart', {})
    p_id = str(product_id)
    if p_id in cart:
        if action == 'add': cart[p_id] += 1
        elif action == 'sub':
            cart[p_id] -= 1
            if cart[p_id] <= 0: cart.pop(p_id)
        elif action == 'remove': cart.pop(p_id)
    session.modified = True
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
        filename = secure_filename(file.filename) if file and allowed_file(file.filename) else None
        if filename: file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        new_order = Order(
            user_id=current_user.id, full_name=request.form.get('name'), 
            address=request.form.get('address'), phone=request.form.get('phone'), 
            prescription_file=filename, payment_method=request.form.get('payment'),
            total_amount=total, medicines_ordered=", ".join([p.name for p in products])
        )
        db.session.add(new_order)
        db.session.commit()
        send_order_email(new_order, current_user)
        session.pop('cart', None)
        flash("Order Placed! Waiting for Pharmacist verification.", "info")
        return redirect(url_for('my_orders'))
    return render_template('checkout.html', products=products, total=total)

# 7. ADMIN ROUTES
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash("Unauthorized Access!", "danger")
        return redirect(url_for('index'))
    
    products = Product.query.all()
    orders = Order.query.order_by(Order.created_at.desc()).all()
    pending_orders = Order.query.filter_by(verification_status='Pending').all()
    users = User.query.filter_by(role='user').all()
    
    # Logic for Charts
    med_count = Product.query.filter_by(category_id=1).count()
    cos_count = Product.query.filter_by(category_id=2).count()
    inst_count = Product.query.filter_by(category_id=3).count()
    total_rev = sum(o.total_amount for o in orders if o.verification_status != 'Rejected')

    return render_template('admin.html', 
                           products=products, orders=orders, users=users,
                           pending_orders=pending_orders, p_count=len(products), 
                           o_count=len(orders), total_rev=total_rev,
                           med_count=med_count, cos_count=cos_count, inst_count=inst_count,
                           categories=Category.query.all())

@app.route('/admin/add_product', methods=['POST'])
@login_required
def add_product():
    if current_user.role != 'admin': return redirect(url_for('index'))
    new_p = Product(
        sku=request.form.get('sku'), name=request.form.get('name'),
        category_id=request.form.get('category_id'), description=request.form.get('description'),
        price=float(request.form.get('price')), image_url=request.form.get('image_url')
    )
    db.session.add(new_p)
    db.session.commit()
    flash("Product Added Successfully", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update_status/<int:id>/<string:status>')
@login_required
def update_status(id, status):
    if current_user.role != 'admin': return redirect(url_for('index'))
    order = db.session.get(Order, id)
    if order:
        order.verification_status = status
        db.session.commit()
        flash(f"Order #{id} status updated to {status}", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_product/<int:id>')
@login_required
def delete_product(id):
    if current_user.role != 'admin': return redirect(url_for('index'))
    p = db.session.get(Product, id)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# 8. AUTHENTICATION ROUTES
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        if User.query.filter_by(email=email).first():
            flash("Email already exists!", "danger")
            return redirect(url_for('register'))
        
        otp = str(random.randint(100000, 999999))
        new_user = User(
            username=request.form.get('username'), email=email, phone=request.form.get('phone'),
            password=generate_password_hash(request.form.get('password')),
            lat=request.form.get('lat'), lng=request.form.get('lng'), otp=otp
        )
        db.session.add(new_user)
        db.session.commit()
        send_otp_email(email, otp)
        session['verify_user_id'] = new_user.id
        return redirect(url_for('verify_otp'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            # Admin-ah irundha direct-ah dashboard-ku poga
            if user.role == 'admin': return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
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
            return redirect(url_for('index'))
        flash('Invalid OTP', 'danger')
    return render_template('verify_otp.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/my_orders')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template('orders.html', orders=orders)

@app.route('/track/<int:order_id>')
@login_required
def track_order(order_id):
    order = db.session.get(Order, order_id)
    user_coords = [float(current_user.lat or 13.08), float(current_user.lng or 80.27)]
    return render_template('track.html', order=order, user=user_coords)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Create default Admin if not exists
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', email='admin@medikart.com', phone='000', 
                         password=generate_password_hash('admin123'), role='admin', is_active=True)
            db.session.add(admin)
            # Create Default Categories
            if not Category.query.first():
                db.session.add(Category(name="Medicines"))
                db.session.add(Category(name="Wellness"))
                db.session.add(Category(name="Personal Care"))
            db.session.commit()
            print("Admin account and Categories created!")

    app.run(debug=True)