from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json
import os
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal
import logging

app = Flask(__name__)
app.secret_key = 'your_secret_key_change_in_production'

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# AWS Configuration
AWS_REGION = 'ap-south-1'
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:bookbazartopic'

# SES Configuration - Replace with your verified email domain
SES_FROM_EMAIL = 'bookbazar@yourdomain.com'  # Must be verified in SES
# Note: For production, verify your domain in SES or verify individual email addresses

# Initialize AWS clients
try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    sns = boto3.client('sns', region_name=AWS_REGION)
    ses = boto3.client('ses', region_name=AWS_REGION)
    
    # Get table references
    users_table = dynamodb.Table('users')
    carts_table = dynamodb.Table('carts')
    
    logger.info("AWS services initialized successfully")
except Exception as e:
    logger.error(f"Error initializing AWS services: {e}")
    raise

def load_books():
    """Load books data from JSON file"""
    try:
        books_path = os.path.join('data', 'books.json')
        with open(books_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Return sample data if file doesn't exist
        return [
            {
                "id": 1,
                "title": "The Great Gatsby",
                "author": "F. Scott Fitzgerald",
                "price": 12.99,
                "image": "images/gatsby.jpg",
                "description": "A classic American novel set in the Jazz Age."
            },
            {
                "id": 2,
                "title": "To Kill a Mockingbird",
                "author": "Harper Lee",
                "price": 14.99,
                "image": "images/mockingbird.jpg",
                "description": "A gripping tale of racial injustice and childhood innocence."
            },
            {
                "id": 3,
                "title": "1984",
                "author": "George Orwell",
                "price": 13.99,
                "image": "images/1984.jpg",
                "description": "A dystopian social science fiction novel."
            },
            {
                "id": 4,
                "title": "Pride and Prejudice",
                "author": "Jane Austen",
                "price": 11.99,
                "image": "images/pride.jpg",
                "description": "A romantic novel of manners."
            }
        ]

def decimal_to_float(obj):
    """Convert DynamoDB Decimal to float for JSON serialization"""
    if isinstance(obj, list):
        return [decimal_to_float(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: decimal_to_float(value) for key, value in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    return obj

def get_user_from_db(username):
    """Get user from DynamoDB"""
    try:
        response = users_table.get_item(Key={'username': username})
        return response.get('Item')
    except ClientError as e:
        logger.error(f"Error getting user {username}: {e}")
        return None

def create_user_in_db(username, password):
    """Create user in DynamoDB"""
    try:
        users_table.put_item(
            Item={
                'username': username,
                'password': password
            },
            ConditionExpression='attribute_not_exists(username)'
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False  # User already exists
        logger.error(f"Error creating user {username}: {e}")
        return False

def get_user_cart(username):
    """Get user's cart from DynamoDB"""
    try:
        response = carts_table.get_item(Key={'username': username})
        if 'Item' in response:
            cart_data = response['Item']
            return decimal_to_float(cart_data.get('items', []))
        return []
    except ClientError as e:
        logger.error(f"Error getting cart for {username}: {e}")
        return []

def update_user_cart(username, cart_items):
    """Update user's cart in DynamoDB"""
    try:
        # Convert floats to Decimal for DynamoDB
        decimal_items = json.loads(json.dumps(cart_items), parse_float=Decimal)
        
        carts_table.put_item(
            Item={
                'username': username,
                'items': decimal_items
            }
        )
        return True
    except ClientError as e:
        logger.error(f"Error updating cart for {username}: {e}")
        return False

def send_notification(subject, message, email=None):
    """Send SNS notification or SES email"""
    try:
        if email:
            # Send direct email using SES
            ses.send_email(
                Source=SES_FROM_EMAIL,
                Destination={'ToAddresses': [email]},
                Message={
                    'Subject': {'Data': subject},
                    'Body': {'Text': {'Data': message}}
                }
            )
            logger.info(f"Email sent to: {email}")
        else:
            # Send to SNS topic (for admin notifications)
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=subject,
                Message=message
            )
            logger.info(f"Topic notification sent: {subject}")
    except ClientError as e:
        logger.error(f"Error sending notification: {e}")
        # Fallback: try SNS direct publish if SES fails
        if email:
            try:
                sns.publish(
                    Subject=f"{subject} - Customer: {email}",
                    Message=f"Customer Email: {email}\n\n{message}",
                    TopicArn=SNS_TOPIC_ARN
                )
                logger.info(f"Fallback SNS notification sent for {email}")
            except ClientError as fallback_error:
                logger.error(f"Fallback notification also failed: {fallback_error}")

def find_book_by_id(book_id):
    """Find a book by its ID"""
    books = load_books()
    for book in books:
        if book['id'] == book_id:
            return book
    return None

# Home route - show index.html landing page
@app.route('/')
def home():
    return render_template('index.html')

# Index route (alias for home)
@app.route('/index')
def index():
    return render_template('index.html')

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        # Validation
        if not username or not password:
            flash('Username and password are required!', 'error')
            return render_template('register.html')

        if len(password) < 1:
            flash('Password cannot be empty!', 'error')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return render_template('register.html')

        # Check if user already exists
        if get_user_from_db(username):
            flash('Username already exists!', 'error')
            return render_template('register.html')

        # Register user
        if create_user_in_db(username, password):
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Registration failed. Please try again.', 'error')
            return render_template('register.html')

    return render_template('register.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Username and password are required!', 'error')
            return render_template('login.html')

        user = get_user_from_db(username)
        if user and user.get('password') == password:
            session['username'] = username
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('books'))
        else:
            flash('Invalid username or password!', 'error')
            return render_template('login.html')

    return render_template('login.html')

# Books route (main library) - requires login
@app.route('/books')
def books():
    if 'username' not in session:
        flash('Please login to access the library.', 'error')
        return redirect(url_for('login'))

    books_data = load_books()
    username = session['username']
    cart_items = get_user_cart(username)
    cart_count = sum(item['quantity'] for item in cart_items)
    return render_template('books.html', books=books_data, cart_count=cart_count)

# Add to cart route
@app.route('/add_to_cart/<int:book_id>')
def add_to_cart(book_id):
    if 'username' not in session:
        flash('Please login to add items to cart.', 'error')
        return redirect(url_for('login'))

    username = session['username']
    book = find_book_by_id(book_id)
    
    if not book:
        flash('Book not found!', 'error')
        return redirect(url_for('books'))

    cart = get_user_cart(username)
    
    # Check if book already in cart
    for item in cart:
        if item['id'] == book_id:
            item['quantity'] += 1
            update_user_cart(username, cart)
            flash(f'Increased quantity of "{book["title"]}" in cart!', 'success')
            return redirect(url_for('books'))
    
    # Add new item to cart
    cart_item = book.copy()
    cart_item['quantity'] = 1
    cart.append(cart_item)
    update_user_cart(username, cart)
    
    flash(f'"{book["title"]}" added to cart!', 'success')
    return redirect(url_for('books'))

# Cart page
@app.route('/cart')
def cart():
    if 'username' not in session:
        flash('Please login to view your cart.', 'error')
        return redirect(url_for('login'))

    username = session['username']
    cart_items = get_user_cart(username)
    
    # Calculate total
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    
    return render_template('cart.html', cart_items=cart_items, total=total)

# Update cart quantity
@app.route('/update_cart/<int:book_id>/<action>')
def update_cart(book_id, action):
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    cart = get_user_cart(username)
    
    for i, item in enumerate(cart):
        if item['id'] == book_id:
            if action == 'increase':
                item['quantity'] += 1
            elif action == 'decrease':
                if item['quantity'] > 1:
                    item['quantity'] -= 1
                else:
                    cart.pop(i)
                    flash(f'"{item["title"]}" removed from cart!', 'info')
            elif action == 'remove':
                cart.pop(i)
                flash(f'"{item["title"]}" removed from cart!', 'info')
            break
    
    update_user_cart(username, cart)
    return redirect(url_for('cart'))

# Checkout page
@app.route('/checkout')
def checkout():
    if 'username' not in session:
        flash('Please login to checkout.', 'error')
        return redirect(url_for('login'))

    username = session['username']
    cart_items = get_user_cart(username)
    
    if not cart_items:
        flash('Your cart is empty!', 'error')
        return redirect(url_for('cart'))
    
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    return render_template('checkout.html', cart_items=cart_items, total=total)

# Process checkout
@app.route('/process_checkout', methods=['POST'])
def process_checkout():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    cart_items = get_user_cart(username)
    
    if not cart_items:
        flash('Your cart is empty!', 'error')
        return redirect(url_for('cart'))

    # Get form data
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    address = request.form.get('address', '').strip()
    payment_method = request.form.get('payment_method', '')

    # Basic validation
    if not all([name, email, address, payment_method]):
        flash('All fields are required!', 'error')
        return redirect(url_for('checkout'))

    # Process order (in real app, integrate with payment gateway)
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    
    # Send order confirmation email to customer
    customer_message = f"""
    Dear {name},
    
    Thank you for your order at BookBazar!
    
    Order Details:
    Total Amount: ${total:.2f}
    
    Items Ordered:
    """
    
    for item in cart_items:
        customer_message += f"- {item['title']} by {item['author']} x {item['quantity']} = ${item['price'] * item['quantity']:.2f}\n"
    
    customer_message += f"""
    
    Shipping Address: {address}
    Payment Method: {payment_method}
    
    Your order will be processed within 24 hours.
    
    Thank you for shopping with BookBazar!
    """
    
    # Send email notification to customer
    send_notification(
        'Order Confirmation - BookBazar',
        customer_message,
        email
    )
    
    # Send order notification to admin/topic
    admin_message = f"""
    New Order Received - BookBazar
    
    Customer: {name}
    Email: {email}
    Address: {address}
    Payment Method: {payment_method}
    Total Amount: ${total:.2f}
    
    Items:
    """
    
    for item in cart_items:
        admin_message += f"- {item['title']} x {item['quantity']} = ${item['price'] * item['quantity']:.2f}\n"
    
    send_notification('New Order - BookBazar', admin_message)
    
    # Clear cart after successful order
    update_user_cart(username, [])
    
    # Redirect to confirmation with order details
    return render_template('confirmation.html', 
                         order_total=total, 
                         customer_name=name,
                         customer_email=email)

# Library route (alternative view) - requires login
@app.route('/library')
def library():
    if 'username' not in session:
        flash('Please login to access the library.', 'error')
        return redirect(url_for('login'))

    books_data = load_books()
    username = session['username']
    cart_items = get_user_cart(username)
    cart_count = sum(item['quantity'] for item in cart_items)
    return render_template('library.html', books=books_data, cart_count=cart_count)

# API endpoint to get cart count
@app.route('/api/cart_count')
def cart_count():
    if 'username' not in session:
        return jsonify({'count': 0})
    
    username = session['username']
    cart_items = get_user_cart(username)
    count = sum(item['quantity'] for item in cart_items)
    return jsonify({'count': count})

# User profile/account page
@app.route('/account')
def account():
    if 'username' not in session:
        flash('Please login to view your account.', 'error')
        return redirect(url_for('login'))
    
    username = session['username']
    cart_items = get_user_cart(username)
    cart_count = sum(item['quantity'] for item in cart_items)
    return render_template('account.html', username=username, cart_count=cart_count)

# Browse books (public route - doesn't require login, shows limited info)
@app.route('/browse')
def browse():
    books_data = load_books()
    return render_template('browse.html', books=books_data)

# About page
@app.route('/about')
def about():
    return render_template('about.html')

# Contact page  
@app.route('/contact')
def contact():
    return render_template('contact.html')

# FAQ page
@app.route('/faq')
def faq():
    return render_template('faq.html')

# Terms page
@app.route('/terms')
def terms():
    return render_template('terms.html')

# Privacy policy page
@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

# Logout
@app.route('/logout')
def logout():
    username = session.get('username', 'User')
    session.clear()
    flash(f'Goodbye, {username}! You have been logged out.', 'info')
    return redirect(url_for('home'))

if __name__ == '__main__':
    # Create data directory if it doesn't exist
    os.makedirs('data', exist_ok=True)
    
    # Create sample books.json if it doesn't exist
    books_path = os.path.join('data', 'books.json')
    if not os.path.exists(books_path):
        sample_books = [
            {
                "id": 1,
                "title": "The Great Gatsby",
                "author": "F. Scott Fitzgerald",
                "price": 12.99,
                "image": "images/gatsby.jpg",
                "description": "A classic American novel set in the Jazz Age."
            },
            {
                "id": 2,
                "title": "To Kill a Mockingbird",
                "author": "Harper Lee",
                "price": 14.99,
                "image": "images/mockingbird.jpg",
                "description": "A gripping tale of racial injustice and childhood innocence."
            },
            {
                "id": 3,
                "title": "1984",
                "author": "George Orwell",
                "price": 13.99,
                "image": "images/1984.jpg",
                "description": "A dystopian social science fiction novel."
            },
            {
                "id": 4,
                "title": "Pride and Prejudice",
                "author": "Jane Austen",
                "price": 11.99,
                "image": "images/pride.jpg",
                "description": "A romantic novel of manners."
            },
            {
                "id": 5,
                "title": "Atomic Habits",
                "author": "James Clear",
                "price": 16.99,
                "image": "images/atomic_habits.jpg",
                "description": "An Easy & Proven Way to Build Good Habits & Break Bad Ones."
            },
            {
                "id": 6,
                "title": "Rich Dad Poor Dad",
                "author": "Robert Kiyosaki",
                "price": 15.99,
                "image": "images/rich_dad_poor_dad.jpg",
                "description": "What the Rich Teach Their Kids About Money That the Poor and Middle Class Do Not!"
            },
            {
                "id": 7,
                "title": "The Alchemist",
                "author": "Paulo Coelho",
                "price": 13.50,
                "image": "images/the_alchemist.jpg",
                "description": "A magical story about following your dreams."
            }
        ]
        
        with open(books_path, 'w') as f:
            json.dump(sample_books, f, indent=2)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
