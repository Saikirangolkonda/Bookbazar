from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import json
import os
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from decimal import Decimal
import logging
from datetime import datetime
import pytz
import uuid

app = Flask(__name__)
app.secret_key = 'your_secret_key_change_in_production'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# AWS Configuration
AWS_REGION = 'ap-south-1'
SNS_TOPIC_ARN = 'arn:aws:sns:ap-south-1:686255965861:bookbazartopic'

# Initialize AWS clients with better error handling
def initialize_aws_services():
    """Initialize AWS services with proper error handling"""
    try:
        # Initialize with explicit region
        dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
        sns = boto3.client('sns', region_name=AWS_REGION)
        
        # Test DynamoDB connection
        users_table = dynamodb.Table('users')
        carts_table = dynamodb.Table('carts')
        
        # Test table existence
        users_table.load()
        carts_table.load()
        
        logger.info("AWS services initialized successfully")
        return dynamodb, sns, users_table, carts_table
        
    except NoCredentialsError:
        logger.error("AWS credentials not found. Please configure your credentials.")
        raise
    except ClientError as e:
        logger.error(f"AWS ClientError: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error initializing AWS services: {e}")
        raise

# Initialize AWS services
try:
    dynamodb, sns, users_table, carts_table = initialize_aws_services()
except Exception as e:
    logger.error(f"Failed to initialize AWS services: {e}")
    # For development, you might want to continue without AWS
    dynamodb = sns = users_table = carts_table = None

def load_books():
    """Load books data from JSON file with fallback"""
    try:
        books_path = os.path.join('data', 'books.json')
        if os.path.exists(books_path):
            with open(books_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading books from file: {e}")
    
    # Return sample data if file doesn't exist or fails to load
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
        },
        {
            "id": 5,
            "title": "Atomic Habits",
            "author": "James Clear",
            "price": 16.99,
            "image": "images/atomic_habits.jpg",
            "description": "An Easy & Proven Way to Build Good Habits & Break Bad Ones."
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
    """Get user from DynamoDB with error handling"""
    if not users_table:
        logger.error("Users table not initialized")
        return None
    
    try:
        response = users_table.get_item(Key={'username': username})
        return response.get('Item')
    except ClientError as e:
        logger.error(f"Error getting user {username}: {e}")
        return None

def create_user_in_db(username, password):
    """Create user in DynamoDB with error handling"""
    if not users_table:
        logger.error("Users table not initialized")
        return False
    
    try:
        users_table.put_item(
            Item={
                'username': username,
                'password': password,
                'created_at': datetime.now().isoformat()
            },
            ConditionExpression='attribute_not_exists(username)'
        )
        logger.info(f"User {username} created successfully")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            logger.info(f"User {username} already exists")
            return False
        logger.error(f"Error creating user {username}: {e}")
        return False

def get_user_cart(username):
    """Get user's cart from DynamoDB with error handling"""
    if not carts_table:
        logger.error("Carts table not initialized")
        return []
    
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
    """Update user's cart in DynamoDB with error handling"""
    if not carts_table:
        logger.error("Carts table not initialized")
        return False
    
    try:
        # Convert floats to Decimal for DynamoDB
        decimal_items = json.loads(json.dumps(cart_items), parse_float=Decimal)
        
        carts_table.put_item(
            Item={
                'username': username,
                'items': decimal_items,
                'updated_at': datetime.now().isoformat()
            }
        )
        return True
    except ClientError as e:
        logger.error(f"Error updating cart for {username}: {e}")
        return False

def get_local_time():
    """Get current time in Indian timezone"""
    try:
        india_tz = pytz.timezone('Asia/Kolkata')
        return datetime.now(india_tz).strftime("%Y-%m-%d %H:%M:%S IST")
    except Exception as e:
        logger.error(f"Error getting local time: {e}")
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def generate_order_id():
    """Generate a unique order ID"""
    return f"ORD-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

def send_order_confirmation_notification(username, cart_items, customer_info, total_amount, order_id):
    """Send detailed order confirmation notification"""
    if not sns:
        logger.error("SNS client not initialized")
        return False
    
    try:
        logger.info(f"Sending notification for order {order_id} - user: {username}")
        
        # Generate order timestamp
        order_time = get_local_time()
        
        # Build detailed notification message
        message = f"""🎉 ORDER CONFIRMED - BookBazar 📚

Order ID: {order_id}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📅 Order Date: {order_time}
👤 Customer: {customer_info['name']}
📧 Email: {customer_info['email']}
📍 Address: {customer_info['address']}
💳 Payment: {customer_info['payment_method']}

📖 BOOKS ORDERED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

        total_books = 0
        for item in cart_items:
            quantity = item.get('quantity', 1)
            price = float(item.get('price', 0))
            item_total = quantity * price
            total_books += quantity
            
            message += f"""
📚 {item.get('title', 'Unknown Title')}
   ✍️  By: {item.get('author', 'Unknown Author')}
   💰 Price: ${price:.2f} x {quantity}
   💵 Subtotal: ${item_total:.2f}"""

        message += f"""

💰 ORDER SUMMARY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📚 Total Books: {total_books}
💵 Total Amount: ${total_amount:.2f}

✅ Status: Order Confirmed
🚚 Delivery: 3-5 Business Days

Thank you for choosing BookBazar! 📚✨
Support: support@bookbazar.com
"""

        # Send the notification
        response = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f'📚 Order {order_id} Confirmed - ${total_amount:.2f}',
            Message=message
        )
        
        logger.info(f"Notification sent successfully for order {order_id}")
        logger.info(f"SNS MessageId: {response.get('MessageId', 'Unknown')}")
        return True
        
    except ClientError as e:
        logger.error(f"AWS ClientError sending notification: {e}")
        logger.error(f"Error Code: {e.response['Error']['Code']}")
        logger.error(f"Error Message: {e.response['Error']['Message']}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending notification: {e}")
        return False

def find_book_by_id(book_id):
    """Find a book by its ID"""
    books = load_books()
    for book in books:
        if book['id'] == book_id:
            return book
    return None

# Routes

@app.route('/')
def home():
    """Home page"""
    return render_template('index.html')

@app.route('/index')
def index():
    """Index page (alias for home)"""
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        # Validation
        if not username or not password:
            flash('Username and password are required!', 'error')
            return render_template('register.html')

        if len(username) < 3:
            flash('Username must be at least 3 characters long!', 'error')
            return render_template('register.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters long!', 'error')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return render_template('register.html')

        # Check if user already exists
        if get_user_from_db(username):
            flash('Username already exists! Please choose a different one.', 'error')
            return render_template('register.html')

        # Register user
        if create_user_in_db(username, password):
            flash('Registration successful! Please login to continue.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Registration failed. Please try again.', 'error')
            return render_template('register.html')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Please enter both username and password!', 'error')
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

@app.route('/books')
def books():
    """Books catalog page - requires login"""
    if 'username' not in session:
        flash('Please login to access the book catalog.', 'error')
        return redirect(url_for('login'))

    books_data = load_books()
    username = session['username']
    cart_items = get_user_cart(username)
    cart_count = sum(item.get('quantity', 0) for item in cart_items)
    
    return render_template('books.html', books=books_data, cart_count=cart_count)

@app.route('/add_to_cart/<int:book_id>')
def add_to_cart(book_id):
    """Add book to cart"""
    if 'username' not in session:
        flash('Please login to add items to your cart.', 'error')
        return redirect(url_for('login'))

    username = session['username']
    book = find_book_by_id(book_id)
    
    if not book:
        flash('Book not found!', 'error')
        return redirect(url_for('books'))

    cart = get_user_cart(username)
    
    # Check if book already in cart
    book_exists = False
    for item in cart:
        if item['id'] == book_id:
            item['quantity'] = item.get('quantity', 0) + 1
            book_exists = True
            break
    
    if not book_exists:
        # Add new item to cart
        cart_item = book.copy()
        cart_item['quantity'] = 1
        cart.append(cart_item)
    
    if update_user_cart(username, cart):
        flash(f'"{book["title"]}" added to cart!', 'success')
    else:
        flash('Failed to add item to cart. Please try again.', 'error')
    
    return redirect(url_for('books'))

@app.route('/cart')
def cart():
    """Shopping cart page"""
    if 'username' not in session:
        flash('Please login to view your cart.', 'error')
        return redirect(url_for('login'))

    username = session['username']
    cart_items = get_user_cart(username)
    
    # Calculate total
    total = sum(float(item.get('price', 0)) * item.get('quantity', 0) for item in cart_items)
    
    return render_template('cart.html', cart_items=cart_items, total=total)

@app.route('/update_cart/<int:book_id>/<action>')
def update_cart(book_id, action):
    """Update cart item quantity"""
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    cart = get_user_cart(username)
    
    for i, item in enumerate(cart):
        if item['id'] == book_id:
            if action == 'increase':
                item['quantity'] = item.get('quantity', 0) + 1
            elif action == 'decrease':
                if item.get('quantity', 0) > 1:
                    item['quantity'] -= 1
                else:
                    removed_item = cart.pop(i)
                    flash(f'"{removed_item.get("title", "Item")}" removed from cart!', 'info')
            elif action == 'remove':
                removed_item = cart.pop(i)
                flash(f'"{removed_item.get("title", "Item")}" removed from cart!', 'info')
            break
    
    update_user_cart(username, cart)
    return redirect(url_for('cart'))

@app.route('/checkout')
def checkout():
    """Checkout page"""
    if 'username' not in session:
        flash('Please login to proceed with checkout.', 'error')
        return redirect(url_for('login'))

    username = session['username']
    cart_items = get_user_cart(username)
    
    if not cart_items:
        flash('Your cart is empty! Add some books first.', 'error')
        return redirect(url_for('books'))
    
    total = sum(float(item.get('price', 0)) * item.get('quantity', 0) for item in cart_items)
    return render_template('checkout.html', cart_items=cart_items, total=total)

@app.route('/process_checkout', methods=['POST'])
def process_checkout():
    """Process the checkout and send notification"""
    if 'username' not in session:
        flash('Please login to complete your order.', 'error')
        return redirect(url_for('login'))

    username = session['username']
    cart_items = get_user_cart(username)
    
    if not cart_items:
        flash('Your cart is empty!', 'error')
        return redirect(url_for('cart'))

    # Get and validate form data
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    address = request.form.get('address', '').strip()
    payment_method = request.form.get('payment_method', '').strip()

    if not all([name, email, address, payment_method]):
        flash('All fields are required to complete your order!', 'error')
        return redirect(url_for('checkout'))

    # Basic email validation
    if '@' not in email or '.' not in email:
        flash('Please enter a valid email address!', 'error')
        return redirect(url_for('checkout'))

    # Calculate total
    total = sum(float(item.get('price', 0)) * item.get('quantity', 0) for item in cart_items)
    
    # Generate unique order ID
    order_id = generate_order_id()
    
    # Prepare customer info
    customer_info = {
        'name': name,
        'email': email,
        'address': address,
        'payment_method': payment_method
    }
    
    # Send order confirmation notification
    notification_sent = send_order_confirmation_notification(
        username, cart_items, customer_info, total, order_id
    )
    
    # Clear cart after successful order
    if update_user_cart(username, []):
        if notification_sent:
            flash(f'Order {order_id} placed successfully! Confirmation notification sent.', 'success')
        else:
            flash(f'Order {order_id} placed successfully! (Notification may be delayed)', 'warning')
    else:
        flash('Order processed but cart update failed. Please contact support.', 'warning')
    
    # Redirect to confirmation page
    return render_template('confirmation.html', 
                         order_id=order_id,
                         order_total=total, 
                         customer_name=name,
                         customer_email=email,
                         notification_sent=notification_sent)

@app.route('/test_sns')
def test_sns():
    """Test SNS connectivity"""
    if 'username' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))
    
    try:
        if not sns:
            flash('SNS client not initialized. Check AWS configuration.', 'error')
            return redirect(url_for('books'))
        
        test_message = f"Test notification from BookBazar at {get_local_time()}"
        response = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject='BookBazar - Test Notification',
            Message=test_message
        )
        
        logger.info(f"SNS test successful: {response}")
        flash('SNS test successful! Notifications are working properly.', 'success')
        
    except Exception as e:
        logger.error(f"SNS test failed: {e}")
        flash(f'SNS test failed: {str(e)}', 'error')
    
    return redirect(url_for('books'))

@app.route('/api/cart_count')
def api_cart_count():
    """API endpoint to get cart count"""
    if 'username' not in session:
        return jsonify({'count': 0})
    
    username = session['username']
    cart_items = get_user_cart(username)
    count = sum(item.get('quantity', 0) for item in cart_items)
    return jsonify({'count': count})

@app.route('/account')
def account():
    """User account page"""
    if 'username' not in session:
        flash('Please login to view your account.', 'error')
        return redirect(url_for('login'))
    
    username = session['username']
    cart_items = get_user_cart(username)
    cart_count = sum(item.get('quantity', 0) for item in cart_items)
    
    return render_template('account.html', username=username, cart_count=cart_count)

@app.route('/browse')
def browse():
    """Browse books (public access)"""
    books_data = load_books()
    return render_template('browse.html', books=books_data)

@app.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@app.route('/contact')
def contact():
    """Contact page"""
    return render_template('contact.html')

@app.route('/logout')
def logout():
    """User logout"""
    username = session.get('username', 'User')
    session.clear()
    flash(f'Goodbye, {username}! You have been logged out successfully.', 'info')
    return redirect(url_for('home'))

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return render_template('500.html'), 500

def create_sample_data():
    """Create sample books data file"""
    os.makedirs('data', exist_ok=True)
    
    books_path = os.path.join('data', 'books.json')
    if not os.path.exists(books_path):
        sample_books = [
            {
                "id": 1,
                "title": "The Great Gatsby",
                "author": "F. Scott Fitzgerald",
                "price": 12.99,
                "image": "images/gatsby.jpg",
                "description": "A classic American novel set in the Jazz Age, exploring themes of wealth, love, and the American Dream."
            },
            {
                "id": 2,
                "title": "To Kill a Mockingbird",
                "author": "Harper Lee",
                "price": 14.99,
                "image": "images/mockingbird.jpg",
                "description": "A gripping tale of racial injustice and childhood innocence in the American South."
            },
            {
                "id": 3,
                "title": "1984",
                "author": "George Orwell",
                "price": 13.99,
                "image": "images/1984.jpg",
                "description": "A dystopian social science fiction novel about totalitarian control and surveillance."
            },
            {
                "id": 4,
                "title": "Pride and Prejudice",
                "author": "Jane Austen",
                "price": 11.99,
                "image": "images/pride.jpg",
                "description": "A romantic novel of manners set in Georgian England."
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
                "description": "A magical story about following your dreams and finding your personal legend."
            }
        ]
        
        try:
            with open(books_path, 'w', encoding='utf-8') as f:
                json.dump(sample_books, f, indent=2, ensure_ascii=False)
            logger.info("Sample books data created successfully")
        except Exception as e:
            logger.error(f"Error creating sample books data: {e}")

if __name__ == '__main__':
    # Create sample data if needed
    create_sample_data()
    
    # Run the application
    logger.info("Starting BookBazar application...")
    app.run(host='0.0.0.0', port=5000, debug=True)
