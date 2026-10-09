-- Golden shop schema for the AI-drafting manual eval protocol
-- (docs/ai-drafting-eval.md). Inventory: 8 tables, 7 FKs, UNIQUE sku /
-- username / email, status + *_type columns for enum-like decisions.
-- Edit together with test_golden_reflect.py and the eval doc.

CREATE TABLE "user" (
    id INTEGER PRIMARY KEY,
    username VARCHAR(40) NOT NULL UNIQUE,
    email VARCHAR(120) NOT NULL UNIQUE,
    role VARCHAR(20) DEFAULT 'user',
    created_at TIMESTAMP
);

CREATE TABLE customer (
    id INTEGER PRIMARY KEY,
    ref_user_id INTEGER NOT NULL,
    name VARCHAR(80) NOT NULL,
    phone VARCHAR(30),
    vip BOOLEAN DEFAULT 0,
    registered_at TIMESTAMP,
    FOREIGN KEY (ref_user_id) REFERENCES "user"(id)
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    order_type VARCHAR(20),
    total DECIMAL(12, 2),
    created_at TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customer(id)
);

CREATE TABLE category (
    id INTEGER PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    sort INTEGER
);

CREATE TABLE product (
    id INTEGER PRIMARY KEY,
    category_id INTEGER,
    sku VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    status VARCHAR(20),
    price DECIMAL(10, 2),
    FOREIGN KEY (category_id) REFERENCES category(id)
);

CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10, 2),
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES product(id)
);

CREATE TABLE address (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    address_type VARCHAR(20),
    province VARCHAR(40),
    city VARCHAR(40),
    detail VARCHAR(200),
    is_default BOOLEAN DEFAULT 0,
    FOREIGN KEY (customer_id) REFERENCES customer(id)
);

CREATE TABLE payment (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    pay_type VARCHAR(20) NOT NULL,
    amount DECIMAL(12, 2),
    paid_at TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

-- SQLite's inspector does not surface inline UNIQUE constraints as indexes
-- (PG/MySQL do), so unique-ness is declared twice: inline above for those
-- dialects, explicitly here for the SQLite reflection path.
CREATE UNIQUE INDEX ix_user_username ON "user"(username);
CREATE UNIQUE INDEX ix_user_email ON "user"(email);
CREATE UNIQUE INDEX ix_product_sku ON product(sku);
