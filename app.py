from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from fpdf import FPDF 
from flask import make_response
import os

# ---------------- APP CONFIG ----------------
app = Flask(__name__)
app.secret_key = "pharmacy_secret_key"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'pharmacy.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# ---------------- FILE UPLOAD CONFIG ----------------
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


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200))
    image_url = db.Column(db.String(200))


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    full_name = db.Column(db.String(100))
    address = db.Column(db.String(500))
    phone = db.Column(db.String(20))
    prescription_file = db.Column(db.String(200))
    payment_method = db.Column(db.String(50))
    total_amount = db.Column(db.Float)

# ---------------- LOGIN MANAGER ----------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- DATABASE INIT ----------------
with app.app_context():
    db.create_all()

    if not Product.query.first():
        products = [
            Product(name="Paracetamol", price=25, description="Pain relief", image_url="https://via.placeholder.com/150"),
            Product(name="Vitamin C", price=150, description="Immunity booster", image_url="https://via.placeholder.com/150"),
            Product(name="Amoxicillin", price=120, description="Antibiotic", image_url="https://via.placeholder.com/150")
        ]
        db.session.add_all(products)
        db.session.commit()

# ---------------- ROUTES ----------------
@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    if q:
        products = Product.query.filter(
            (Product.name.contains(q)) | (Product.description.contains(q))
        ).all()
    else:
        products = Product.query.all()
    return render_template('index.html', products=products)

# ---------------- AUTH ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form['username']
        email = request.form['email']
        pwd = request.form['password']

        if User.query.filter((User.username == uname) | (User.email == email)).first():
            flash("Username or Email already exists", "danger")
            return redirect(url_for('register'))

        hashed = generate_password_hash(pwd)
        user = User(username=uname, email=email, password=hashed)
        db.session.add(user)
        db.session.commit()

        flash("Registration successful!", "success")
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uname = request.form['username']
        pwd = request.form['password']
        user = User.query.filter_by(username=uname).first()

        if user and check_password_hash(user.password, pwd):
            login_user(user)
            return redirect(url_for('index'))

        flash("Invalid credentials", "danger")
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# ---------------- CART ----------------
@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    session.setdefault('cart', [])
    session['cart'].append(product_id)
    session.modified = True
    return redirect(url_for('index'))


@app.route('/cart')
def cart():
    cart_ids = session.get('cart', [])
    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    total = sum(p.price for p in products)
    return render_template('cart.html', products=products, total=total)


@app.route('/clear_cart')
def clear_cart():
    session.pop('cart', None)
    return redirect(url_for('index'))

# ---------------- CHECKOUT ----------------
@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_ids = session.get('cart', [])
    if not cart_ids:
        flash("Cart is empty", "warning")
        return redirect(url_for('index'))

    products = Product.query.filter(Product.id.in_(cart_ids)).all()
    total = sum(p.price for p in products)

    if request.method == 'POST':
        file = request.files.get('prescription')
        filename = None

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        order = Order(
            user_id=current_user.id,
            full_name=request.form['name'],
            address=request.form['address'],
            phone=request.form['phone'],
            prescription_file=filename,
            payment_method=request.form['payment'],
            total_amount=total
        )

        db.session.add(order)
        db.session.commit()
        session.pop('cart', None)

        flash("Order placed successfully!", "success")
        return redirect(url_for('index'))

    return render_template('checkout.html', products=products, total=total)

# ---------------- MY ORDERS ----------------
@app.route('/my_orders')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.id).all()
    return render_template('orders.html', orders=orders)

# ---------------- RUN ----------------
if __name__ == '__main__':
    app.run(debug=True)

# --- Admin Dashboard Route ---
@app.route('/admin')
@login_required
def admin_dashboard():
    # Simple security check: Only user with username 'admin' can enter
    if current_user.username != 'admin':
        flash("Access Denied! Only Admin can access this page.", "danger")
        return redirect(url_for('index'))
    
    products = Product.query.all()
    orders = Order.query.all() # Orders-aiyum admin paakalaam
    return render_template('admin.html', products=products, orders=orders)

# --- Add Product Route ---
@app.route('/admin/add_product', methods=['POST'])
@login_required
def add_product():
    if current_user.username == 'admin':
        name = request.form.get('name')
        price = float(request.form.get('price'))
        desc = request.form.get('description')
        img = request.form.get('image_url')

        new_product = Product(name=name, price=price, description=desc, image_url=img)
        db.session.add(new_product)
        db.session.commit()
        flash("New Medicine Added!", "success")
    return redirect(url_for('admin_dashboard'))

# --- Delete Product Route ---
@app.route('/admin/delete_product/<int:id>')
@login_required
def delete_product(id):
    if current_user.username == 'admin':
        product = Product.query.get(id)
        db.session.delete(product)
        db.session.commit()
        flash("Product Deleted!", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/download_invoice/<int:order_id>')
@login_required
def download_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Security: Order panna user mattum thaan invoice download panna mudiyum
    if order.user_id != current_user.id and current_user.username != 'admin':
        flash("Unauthorized access!", "danger")
        return redirect(url_for('index'))

    # PDF Create pannuvom
    pdf = FPDF()
    pdf.add_page()
    
    # Invoice Header
    pdf.set_font("Arial", 'B', 20)
    pdf.cell(190, 10, "NANBA ONLINE PHARMACY", ln=True, align='C')
    
    pdf.set_font("Arial", '', 12)
    pdf.cell(190, 10, "Official Medical Invoice", ln=True, align='C')
    pdf.ln(10) # Line break
    
    # Order Details
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(100, 10, f"Invoice ID: #INV-{order.id}")
    pdf.cell(90, 10, f"Date: Today", ln=True, align='R')
    pdf.ln(5)
    
    pdf.set_font("Arial", '', 12)
    pdf.cell(100, 10, f"Customer Name: {order.full_name}")
    pdf.ln(7)
    pdf.cell(100, 10, f"Phone: {order.phone}")
    pdf.ln(7)
    pdf.multi_cell(0, 10, f"Address: {order.address}")
    pdf.ln(10)
    
    # Table Header
    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(130, 10, "Description", border=1, fill=True)
    pdf.cell(60, 10, "Amount", border=1, ln=True, fill=True, align='C')
    
    # Table Body
    pdf.set_font("Arial", '', 12)
    pdf.cell(130, 10, "Medicines (Prescription Based Order)", border=1)
    pdf.cell(60, 10, f"Rs. {order.total_amount}", border=1, ln=True, align='C')
    
    # Total
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(130, 10, "Total Amount Paid:", align='R')
    pdf.cell(60, 10, f"Rs. {order.total_amount}", ln=True, align='C')
    
    pdf.ln(20)
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(190, 10, "Thank you for choosing Nanba Pharmacy! Get well soon.", ln=True, align='C')

    # Response-ah PDF-ah anupuvom
    response = make_response(pdf.output(dest='S').encode('latin-1'))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=invoice_{order.id}.pdf'
    return response