# 🛒 Mall Delivery API

A comprehensive FastAPI-based delivery system for mall vendors and customers, featuring order management, driver assignment, and real-time delivery tracking.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-13+-blue.svg)](https://postgresql.org)
[![Tests](https://img.shields.io/badge/Tests-122%20passing-brightgreen.svg)](#testing)

## 🚀 Features

### 👥 **Multi-Role System**
- **Customers**: Browse stores, place orders, track deliveries
- **Store Owners**: Manage products, view orders, update inventory
- **Drivers**: Accept deliveries, update order status, manage routes
- **Administrators**: System oversight, user management, analytics

### 🏪 **Store Management**
- Store creation and management
- Product catalog with inventory tracking
- Category-based organization
- Owner-specific permissions

### 📦 **Order Processing**
- Shopping cart functionality
- Real-time inventory validation
- Order status tracking (pending → confirmed → assigned → picked up → in transit → delivered)
- Price capture at purchase time

### 🚚 **Delivery System**
- Driver assignment workflow
- Real-time status updates
- Delivery route optimization ready
- Customer notifications

### 🔐 **Security Features**
- JWT-based authentication
- Role-based access control (RBAC)
- Password strength validation
- Environment-based configuration
- Request validation with Pydantic

## 📋 Requirements

- **Python**: 3.11+
- **Database**: PostgreSQL 13+
- **OS**: Linux, macOS, Windows

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/diyeddin/delivery-api.git
cd mall-delivery-api
```

### 2. Set Up Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Configuration
```bash
# Copy the example environment file
cp .env.example .env

# Generate a secure secret key
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"

# Edit .env with your configuration
nano .env
```

### 5. Database Setup
```bash
# Create PostgreSQL database
createdb mall_delivery

# Run migrations
alembic upgrade head
```

### 6. Start the Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at: `http://localhost:8000`

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `SECRET_KEY` | JWT secret key (32+ chars) | - | ✅ |
| `DATABASE_URL` | PostgreSQL connection URL | - | ✅ |
| `ALGORITHM` | JWT algorithm | `HS256` | ❌ |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiration | `60` | ❌ |
| `DEBUG` | Debug mode | `false` | ❌ |
| `ENVIRONMENT` | App environment | `production` | ❌ |

### Example .env file:
```env
SECRET_KEY=your-super-secure-secret-key-here-32-chars-min
DATABASE_URL=postgresql://username:password@localhost:5432/mall_delivery
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
DEBUG=false
ENVIRONMENT=production
```

## 📖 API Documentation

### Authentication
All protected endpoints require a Bearer token in the Authorization header:
```bash
Authorization: Bearer <your-jwt-token>
```

### Base URL
```
http://localhost:8000
```

### Core Endpoints

#### 🔐 Authentication
- `POST /auth/register` - User registration
- `POST /auth/login` - User login

#### 👤 Users
- `GET /users/me` - Get current user profile
- `PATCH /users/{user_id}/role` - Update user role (admin only)

#### 🏪 Stores
- `GET /stores` - List all stores
- `POST /stores` - Create new store
- `GET /stores/{store_id}` - Get store details
- `PUT /stores/{store_id}` - Update store
- `DELETE /stores/{store_id}` - Delete store

#### 📦 Products
- `GET /products` - List all products
- `POST /products` - Create new product
- `GET /products/{product_id}` - Get product details
- `PUT /products/{product_id}` - Update product
- `DELETE /products/{product_id}` - Delete product

#### 🛒 Orders
- `POST /orders` - Create new order
- `GET /orders/me` - Get user's orders
- `GET /orders/{order_id}` - Get order details
- `PATCH /orders/{order_id}/status` - Update order status

#### 🚚 Driver Endpoints
- `GET /drivers/available-orders` - Get available orders
- `POST /drivers/accept-order/{order_id}` - Accept order
- `GET /drivers/my-deliveries` - Get assigned deliveries
- `PATCH /drivers/delivery-status/{order_id}` - Update delivery status

#### 👨‍💼 Admin Endpoints
- `GET /admin/orders` - Get all orders
- `PATCH /admin/orders/{order_id}/cancel` - Cancel order
- `PATCH /admin/orders/{order_id}/confirm` - Confirm order

### Interactive API Documentation
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

## 🧪 Testing

### Run All Tests
```bash
pytest
```

### Run Specific Test Categories
```bash
# Authentication tests
pytest tests/test_auth.py -v

# Order workflow tests  
pytest tests/test_orders.py -v

# Admin functionality tests
pytest tests/test_admin.py -v

# Driver functionality tests
pytest tests/test_drivers.py -v
```

### Test Coverage
```bash
pytest --cov=app tests/
```

### Current Test Stats
- **Total Tests**: 122
- **Pass Rate**: 100%
- **Coverage**: Auth, Orders, Stores, Products, Admin, Drivers

## 🏗️ Project Structure

```
mall-delivery-api/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app instance
│   ├── core/
│   │   ├── config.py          # Environment configuration
│   │   └── security.py        # JWT & password handling
│   ├── db/
│   │   ├── database.py        # Database connection
│   │   └── models.py          # SQLAlchemy models
│   ├── routers/
│   │   ├── auth.py           # Authentication endpoints
│   │   ├── users.py          # User management
│   │   ├── stores.py         # Store operations
│   │   ├── products.py       # Product management
│   │   ├── orders.py         # Order processing
│   │   ├── drivers.py        # Driver operations
│   │   └── admin.py          # Admin panel
│   ├── schemas/
│   │   ├── user.py           # User Pydantic models
│   │   ├── store.py          # Store Pydantic models
│   │   ├── product.py        # Product Pydantic models
│   │   └── order.py          # Order Pydantic models
│   ├── services/
│   │   ├── order_service.py  # Order business logic
│   │   ├── product_service.py # Product business logic
│   │   └── store_service.py  # Store business logic
│   └── utils/
│       ├── dependencies.py   # FastAPI dependencies
│       └── exceptions.py     # Custom exceptions
├── tests/
│   ├── conftest.py           # Test configuration
│   ├── factories.py          # Test data factories
│   └── test_*.py             # Test modules
├── alembic/                  # Database migrations
├── requirements.txt          # Python dependencies
├── .env.example             # Environment template
└── README.md               # This file
```

## 🎯 Usage Examples

### Register a New User
```bash
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "email": "john@example.com",
    "password": "SecurePass123!"
  }'
```

### Login
```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john@example.com&password=SecurePass123!"
```

### Create a Store
```bash
curl -X POST "http://localhost:8000/stores" \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Joe'\''s Pizza",
    "category": "Restaurant",
    "description": "Authentic Italian pizza"
  }'
```

### Place an Order
```bash
curl -X POST "http://localhost:8000/orders" \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "items": [
      {"product_id": 1, "quantity": 2},
      {"product_id": 3, "quantity": 1}
    ]
  }'
```

## 🔄 Order Workflow

```mermaid
graph TD
    A[Customer Places Order] --> B[Order: PENDING]
    B --> C[Admin Reviews] 
    C --> D[Order: CONFIRMED]
    D --> E[Driver Accepts]
    E --> F[Order: ASSIGNED]
    F --> G[Driver Picks Up]
    G --> H[Order: PICKED_UP]
    H --> I[Order: IN_TRANSIT]
    I --> J[Order: DELIVERED]
    
    C --> K[Order: CANCELLED]
    D --> K
    F --> K
```

## 🚀 Deployment

### Production Checklist
- [ ] Generate secure `SECRET_KEY`
- [ ] Set `DEBUG=false`
- [ ] Configure production database
- [ ] Set up SSL/HTTPS
- [ ] Configure proper CORS origins
- [ ] Set up monitoring and logging
- [ ] Configure backup strategy

### Environment Setup
```bash
# Production environment
export ENVIRONMENT=production
export DEBUG=false
export SECRET_KEY="your-production-secret-key"
export DATABASE_URL="postgresql://user:pass@prod-db:5432/mall_delivery"
```

## 🐛 Troubleshooting

### Common Issues

#### Database Connection Error
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Verify database exists
psql -l | grep mall_delivery
```

#### Secret Key Error
```bash
# Generate a new secret key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Migration Issues
```bash
# Reset migrations (development only!)
alembic downgrade base
alembic upgrade head
```

### Debug Mode
Set `DEBUG=true` in `.env` for detailed error messages and automatic reloading.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`pytest`)
5. Commit changes (`git commit -m 'Add amazing feature'`)
6. Push to branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Development Setup
```bash
# Install development dependencies
pip install -r requirements.txt

# Run tests with coverage
pytest --cov=app

# Run linting
flake8 app/
```

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🎯 Roadmap

### Phase 1: Core Features ✅
- [x] User authentication and authorization
- [x] Store and product management
- [x] Order processing workflow
- [x] Driver assignment system
- [x] Admin panel functionality

### Phase 2: Enhancements 🚧
- [ ] Real-time notifications
- [ ] Advanced search and filtering
- [ ] Analytics dashboard
- [ ] Mobile API optimizations
- [ ] Caching layer (Redis)

### Phase 3: Advanced Features 📋
- [ ] Geolocation services
- [ ] Payment integration
- [ ] Review and rating system
- [ ] Inventory forecasting
- [ ] Multi-language support

## 📞 Support

- **Documentation**: Check the `/docs` endpoint for interactive API documentation
- **Issues**: Create an issue on GitHub for bug reports
- **Email**: [Contact the maintainer](mailto:your-email@example.com)

---

**Built with ❤️ using FastAPI, SQLAlchemy, and PostgreSQL**