from app import app, db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    # Create ONE shared branch admin account
    email = "branchadmin@svist.com"
    password = "vahini@123"  # Your password
    
    existing = User.query.filter_by(email=email).first()
    if existing:
        existing.password_hash = generate_password_hash(password)
        print(f"Updated: {email}")
    else:
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            role='branch_admin'  # You'll need to handle this in your code
        )
        db.session.add(user)
        print(f"Created: {email}")
    
    # Create principal
    principal_email = "principal@svist.com"
    principal_existing = User.query.filter_by(email=principal_email).first()
    if principal_existing:
        principal_existing.password_hash = generate_password_hash(password)
    else:
        principal = User(
            email=principal_email,
            password_hash=generate_password_hash(password),
            role='principal'
        )
        db.session.add(principal)
        print(f"Created: {principal_email}")
    
    db.session.commit()