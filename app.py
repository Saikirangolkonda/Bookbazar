from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json
import os
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
import hashlib
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key_change_in_production'

# AWS Configuration
AWS_REGION = 'ap-south-1'
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:bookbazartopic'

# Initialize AWS clients
try:
    dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
    sns = boto3.client('sns', region_name=AWS_REGION)
    
    # Get table references
    users_table = dynamodb.Table('users')
    carts_table = dynamodb.Table('carts')
    
    print("AWS services initialized successfully")
except Exception as e:
    print(f"Error initializing AWS services: {e}")
    dynamodb = None
    sns = None

def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def send_sns_notification(subject, message):
    """Send notification via SNS"""
    try:
        if sns:
            response = sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=subject,
                Message=message
            )
            print(f"SNS notification sent: {response['MessageId']}")
            return True
    except Exception as e:
        print(f"Error sending SNS notification: {e}")
    return False

def create_user(username, password):
    """Create a new user in DynamoDB"""
    try:
        hashed_password = hash_password(password)
        response = users_table.put_item(
            Item={
                'username': username,
                'password': hashed_password,
                'created_at': datetime.now().isoformat(),
                'status': 'active'
            },
            ConditionExpression='attribute_not_exists(username)'
        )
        
        # Send welcome notification
        send_sns_notification(
            subject="New User Registration - BookBazar",
            message=f"New user registered: {username} at {datetime.now().isoformat()}"
        )
        
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False  # Username already exists
        print(f"Error creating user: {e}")
        return False
    except Exception as e:
        print(f"Error creating user: {e}")
        return False

def verify_user(username, password):
    """Verify user credentials"""
    try:
        response = users_table.get_item(
            Key={'username': username}
        )
        
        if 'Item' in response:
            stored_password = response['Item']['password']
            hashed_password = hash_password(password)
            return stored_password == hashed_password
        return False
    except Exception as e:
        print(f"Error verifying user: {e}")
        return False

def get_user_cart(username):
    """Get user's cart from DynamoDB"""
    try:
        response = carts_table.get_item(
            Key={'username': username}
        )
        
        if 'Item' in response:
            return response['Item'].get('cart_items', [])
        return []
    except Exception as e:
        print(f"Error getting user cart: {e}")
        return []

def save_user_cart(username, cart_items):
    """Save user's cart to DynamoDB"""
    try:
        carts_table.put_item(
            Item={
                'username': username,
                'cart_items': cart_items,
                'updated_at': datetime.now().isoformat()
            }
        )
        return True
    except Exception as e:
        print(f"Error saving user cart: {e}")
        return False

def clear_user_cart(username):
    """Clear user's cart in DynamoDB"""
    try:
        carts_table.put_item(
            Item={
                'username': username,
                'cart_items': [],
                'updated_at': datetime.now().isoformat()
            }
        )
        return True
    except Exception as e:
        print(f"Error clearing user cart: {e}")
        return False

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

        if len(password) < 6:
            flash('Password must be at least 6 characters long!', 'error')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return render_template('register.html')

        # Register user
        if create_user(username, password):
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Username already exists or registration failed!', 'error')
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

        if verify_user(username, password):
            session['username'] = username
            flash(f'Welcome back, {username}!', 'success')
            
            # Send login notification
            send_sns_notification(
                subject="User Login - BookBazar",
                message=f"User {username} logged in at {datetime.now().isoformat()}"
            )
            
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
            save_user_cart(username, cart)
            flash(f'Increased quantity of "{book["title"]}" in cart!', 'success')
            return redirect(url_for('books'))
    
    # Add new item to cart
    cart_item = book.copy()
    cart_item['quantity'] = 1
    cart.append(cart_item)
    save_user_cart(username, cart)
    
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
    
    save_user_cart(username, cart)
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

    # Process order
    total = sum(item['price'] * item['quantity'] for item in cart_items)
    
    # Send order notification via SNS
    order_details = f"""
    New Order Placed - BookBazar
    
    Customer: {name}
    Email: {email}
    Username: {username}
    Total: ${total:.2f}
    Payment Method: {payment_method}
    Order Time: {datetime.now().isoformat()}
    
    Items:
    """
    
    for item in cart_items:
        order_details += f"- {item['title']} by {item['author']} (Qty: {item['quantity']}, Price: ${item['price']:.2f})\n"
    
    send_sns_notification(
        subject="New Order - BookBazar",
        message=order_details
    )
    
    # Clear cart after successful order
    clear_user_cart(username)
    
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

# Health check endpoint for AWS
@app.route('/health')
def health_check():
    try:
        # Test DynamoDB connection
        users_table.describe_table()
        carts_table.describe_table()
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'services': ['DynamoDB', 'SNS']
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# Logout
@app.route('/logout')
def logout():
    username = session.get('username', 'User')
    session.clear()
    flash(f'Goodbye, {username}! You have been logged out.', 'info')
    
    # Send logout notification
    send_sns_notification(
        subject="User Logout - BookBazar",
        message=f"User {username} logged out at {datetime.now().isoformat()}"
    )
    
    return redirect(url_for('home'))

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

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