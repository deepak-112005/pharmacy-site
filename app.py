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

# 1. INITIALIZE APP FIRST (Ithu thaan muthala irukanum)
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
app.config['MAIL_USERNAME'] = 'deepaksdpi05@gmail.com' # Replace with your email
app.config['MAIL_PASSWORD'] = 'fsqd medi ftdh syip'    # Replace with your App Password
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
    payment_method = db.Column(db.String(50))
    total_amount = db.Column(db.Float)
    # --- INTHA LINE-AH ADD PANNOUNGA ---
    medicines_ordered = db.Column(db.String(500)) 
    # ----------------------------------
    status = db.Column(db.String(50), default='Processing')
    prescription_file = db.Column(db.String(200))
    verification_status = db.Column(db.String(50), default='Pending')
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 5. HELPERS & NOTIFICATIONS
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_notifications(order, user, products):
    msg_body = f"Hi {user.username},\n\nOrder #MK-{order.id} confirmed!\nTotal: ₹{order.total_amount}\nDelivery Address: {order.address}\n\nGet well soon! - Medi kart"
    try:
        msg = Message(f"Medi kart: Order Confirmed #MK-{order.id}", sender=app.config['MAIL_USERNAME'], recipients=[user.email])
        msg.body = msg_body
        mail.send(msg)
    except Exception as e: print(f"Email Error: {e}")

    try:
        sms_text = f"Medi kart: Order #MK-{order.id} confirmed for ₹{order.total_amount}. Delivery soon!"
        twilio_client.messages.create(body=sms_text, from_=TWILIO_PHONE, to=user.phone)
    except Exception as e: print(f"SMS Error: {e}")

# --- 3. NOTIFICATION HELPER ---
def send_real_notifications(order, user):
    # Email logic
    try:
        msg = Message(f"Medi kart Order Confirmed #MK-{order.id}",
                      sender='your-email@gmail.com', recipients=[user.email])
        msg.body = f"Hi {user.username}, your order for ₹{order.total_amount} is placed using {order.payment_method}. Tracking Link: http://127.0.0.1:5000/track/{order.id}"
        mail.send(msg)
    except: pass

    # SMS logic (Only if phone number starts with +91)
    try:
        twilio_client.messages.create(
            body=f"Medi kart: Order #MK-{order.id} placed! Tracking: http://127.0.0.1:5000/track/{order.id}",
            from_=TWILIO_PHONE, to=user.phone)
    except: pass


# 6. SEED DATA
REAL_PRODUCTS = [
    {"sku": "MED-001", "name": "Dolo 650 Tablet", "price": 30.0, "cat": "MEDICINES", "tags": "fever, paracetamol", "desc": "Relieves fever."},
    {"sku": "COS-001", "name": "Himalaya Face Wash", "price": 110.0, "cat": "COSMETICS & PERSONAL CARE", "tags": "face, acne", "desc": "Neem face wash."}
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

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    # 1. Cart items-ah logic-ku mela define pannanum (GET & POST rendukkum common)
    cart_ids = session.get('cart', [])
    if not cart_ids:
        flash("Your cart is empty!", "warning")
        return redirect(url_for('index'))

    # --- INTHA VARIGAL THAAN MUKKIYAM (Fix) ---
    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    total = sum(p.price for p in products)
    # ----------------------------------------

    if request.method == 'POST':
        file = request.files.get('prescription')
        filename, status = None, "Approved"
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        # Order creation
        new_order = Order(
            user_id=current_user.id, 
            full_name=request.form.get('name'), 
            address=request.form.get('address'), 
            phone=request.form.get('phone'), 
            prescription_file=filename, 
            payment_method=request.form.get('payment'),
            total_amount=total, 
            verification_status=status
        )
        db.session.add(new_order)
        db.session.commit()

        # SMS & Email Send pandrom
        try:
            send_notifications(new_order, current_user, products)
        except Exception as e:
            print(f"Notification Error: {e}")

        session.pop('cart', None)
        flash("Order Placed Successfully!", "success")
        return redirect(url_for('my_orders'))

    # GET Request-la intha products use aagum
    return render_template('checkout.html', products=products, total=total)
# --- OTP Helper Function ---
def send_otp_email(email, otp):
    try:
        msg = Message('Medi kart: Your OTP Verification Code', 
                      sender=app.config['MAIL_USERNAME'], 
                      recipients=[email])
        msg.body = f"Your verification code is: {otp}. It will expire in 5 minutes."
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Mail Error: {e}")
        return False
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.username != 'admin': return redirect(url_for('index'))
    p_count = Product.query.count()
    o_count = Order.query.count()
    total_rev = db.session.query(db.func.sum(Order.total_amount)).scalar() or 0
    
    med_count = Product.query.join(Category).filter(Category.name == 'MEDICINES').count()
    cos_count = Product.query.join(Category).filter(Category.name == 'COSMETICS & PERSONAL CARE').count()
    inst_count = Product.query.join(Category).filter(Category.name == 'MEDICAL INSTRUMENTS').count()
    
    return render_template('admin.html', products=Product.query.all(), orders=Order.query.all(),
                           categories=Category.query.all(), p_count=p_count, o_count=o_count, 
                           total_rev=total_rev, med_count=med_count, cos_count=cos_count, inst_count=inst_count)

# (Register, Login, Logout, Profile, Cart routes remain as before)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        # 1. DATABASE-LA CHECK PANROM (Ithu thaan error-ah thadukkum)
        existing_user = User.query.filter((User.email == email) | (User.username == username)).first()
        
        if existing_user:
            if existing_user.email == email:
                flash('Intha Email already register aagi iruku! Vera email use pannunga.', 'danger')
            else:
                flash('Intha Username already edukapatu vittathu!', 'danger')
            return redirect(url_for('register'))

        # Details-ah session-la temporary-ah save panrom
        otp = str(random.randint(100000, 999999))
        session['temp_user'] = {
            'username': request.form['username'],
            'email': email,
            'password': generate_password_hash(request.form['password']),
            'type': 'register'
        }
        session['otp'] = otp
        
        if send_otp_email(email, otp):
            flash('OTP sent to your email!', 'info')
            return redirect(url_for('verify_otp'))
        else:
            flash('Error sending OTP. Check mail settings.', 'danger')
            
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('index'))

            otp = str(random.randint(100000, 999999))
            session['temp_user'] = {'id': user.id, 'type': 'login', 'email': user.email}
            session['otp'] = otp
            
            send_otp_email(user.email, otp)
            flash('Login OTP sent to your registered email!', 'info')
            return redirect(url_for('verify_otp'))
        else:
            flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.address = request.form.get('address')
        current_user.phone = request.form.get('phone')
        db.session.commit()
        flash('Profile updated!', 'success')
    return render_template('profile.html', user=current_user, order_count=Order.query.filter_by(user_id=current_user.id).count())

@app.route('/update_profile', methods=['POST']) # Intha spelling-ah check pannunga
@login_required
def update_profile():
    current_user.phone = request.form.get('phone')
    current_user.address = request.form.get('address')
    db.session.commit()
    flash('Account updated successfully!', 'success')
    return redirect(url_for('profile'))


@app.route('/cart')
def cart():
    cart_ids = session.get('cart', [])
    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    return render_template('cart.html', products=products, total=sum(p.price for p in products))

@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    session.setdefault('cart', [])
    if product_id not in session['cart']:
        session['cart'].append(product_id); session.modified = True
    return redirect(url_for('cart'))

@app.route('/my_orders')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.id).all()
    return render_template('orders.html', orders=orders)

@app.route('/cancel_order/<int:id>')
@login_required
def cancel_order(id):
    order = Order.query.get_or_404(id)
    
    # Security: Order panna user mattum thaan cancel panna mudiyum
    if order.user_id == current_user.id or current_user.username == 'admin':
        db.session.delete(order)
        db.session.commit()
        flash('Order has been cancelled successfully.', 'info')
    else:
        flash('Unauthorized action!', 'danger')
        
    return redirect(url_for('my_orders'))

@app.route('/download_invoice/<int:order_id>')
@login_required
def download_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, "INVOICE - Medi kart", ln=True, align='C')
    res = make_response(pdf.output(dest='S').encode('latin-1'))
    res.headers['Content-Disposition'] = f'attachment; filename=invoice_{order.id}.pdf'
    res.headers['Content-Type'] = 'application/pdf'; return res

@app.route('/track/<int:order_id>')
@login_required
def track_order(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('track.html', order=order)

@app.route('/admin/add_product', methods=['POST'])
@login_required
def add_product():
    if current_user.username != 'admin': return redirect(url_for('index'))
    new_p = Product(
        sku=request.form.get('sku'),
        name=request.form.get('name'),
        category_id=request.form.get('category_id'),
        price=float(request.form.get('price')),
        description=request.form.get('description'),
        image_url=request.form.get('image_url') or "https://via.placeholder.com/150",
        stock_quantity=100
    )
    db.session.add(new_p)
    db.session.commit()
    flash("Product Added Successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_product/<int:id>')
@login_required
def delete_product(id):
    if current_user.username != 'admin': return redirect(url_for('index'))
    p = Product.query.get(id)
    db.session.delete(p)
    db.session.commit()
    flash("Product Deleted!", "danger")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update_status/<int:id>/<status>')
@login_required
def update_status(id, status):
    if current_user.username != 'admin': return redirect(url_for('index'))
    order = Order.query.get(id)
    order.verification_status = status # Update status (Approved/Packing/Delivered)
    db.session.commit()
    flash(f"Order #{id} status updated to {status}", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/clear_cart')
def clear_cart():
    session.pop('cart', None)
    return redirect(url_for('cart'))

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'otp' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_otp = request.form.get('otp')
        
        if user_otp == session.get('otp'):
            temp_data = session.get('temp_user')
            
            if temp_data['type'] == 'register':
                # Create user in DB
                new_user = User(username=temp_data['username'], 
                                email=temp_data['email'], 
                                password=temp_data['password'])
                db.session.add(new_user)
                db.session.commit()
                flash('Registration Successful!', 'success')
                login_user(new_user)
            
            elif temp_data['type'] == 'login':
                # Login user
                user = User.query.get(temp_data['id'])
                login_user(user)
                flash('Logged in successfully!', 'success')

            # Clear session
            session.pop('otp', None)
            session.pop('temp_user', None)
            return redirect(url_for('index'))
        else:
            flash('Invalid OTP! Try again.', 'danger')

    return render_template('verify_otp.html')
if __name__ == '__main__':
    app.run(debug=True)