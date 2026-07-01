"""Seed a local SQLite DB with sample rows matching the maintenance schema.

Demo/test data ONLY — for trying out the pipeline without a real MySQL
connection. Run from the project root (same folder as `backend/`):

    python -m backend.seed_maintenance_demo

This writes `eiaf.db` to the project root (matching `database.url:
sqlite:///eiaf.db` in config/settings.yaml, which is resolved relative to the
process's current working directory).
"""
import sqlite3, datetime, os

DB_PATH = os.path.join(os.getcwd(), "eiaf.db")
con = sqlite3.connect(DB_PATH)
cur = con.cursor()
cur.executescript("""
CREATE TABLE stores (
  id INTEGER PRIMARY KEY, store_id INTEGER, company_id INTEGER, store_name TEXT,
  address TEXT, city TEXT, state TEXT, zip_code TEXT, latitude REAL, longitude REAL,
  store_phone TEXT, store_email TEXT, manager_email TEXT, manager_name TEXT,
  store_url TEXT, is_active TEXT DEFAULT '1', date_created TEXT
);
CREATE TABLE rosters (
  id INTEGER PRIMARY KEY, emp_id TEXT, first_name TEXT, last_name TEXT, email TEXT,
  job_code TEXT, store_id INTEGER, status INTEGER, start_date TEXT, pay_type TEXT,
  hourly_rate REAL, extension TEXT, phone TEXT, is_trainer INTEGER, date_terminate TEXT,
  date_added TEXT
);
CREATE TABLE equipment_check_items (
  id INTEGER PRIMARY KEY, frequency TEXT, equipment TEXT, check_name TEXT,
  check_description TEXT, sop_url TEXT, display_order INTEGER, severity_level TEXT,
  is_active INTEGER, created_at TEXT, updated_at TEXT
);
CREATE TABLE equipment_maintenance_submissions (
  id INTEGER PRIMARY KEY, store_id TEXT, frequency TEXT, technician TEXT, notes TEXT,
  photo_path TEXT, submitted_at TEXT, ip_address TEXT, gf_entry_id INTEGER
);
CREATE TABLE equipment_maintenance_checks (
  id INTEGER PRIMARY KEY, submission_id INTEGER, check_item_id INTEGER, status TEXT,
  issue_description TEXT
);
CREATE TABLE facility_maintenance_tasks (
  id INTEGER PRIMARY KEY, frequency TEXT, equipment TEXT, task_name TEXT,
  task_details TEXT, sort_order INTEGER, active INTEGER, created_at TEXT, updated_at TEXT
);
CREATE TABLE facility_maintenance_logs (
  id INTEGER PRIMARY KEY, store_id TEXT, date_completed TEXT, service_provider TEXT,
  notes TEXT, receipt_file TEXT, certificate_file TEXT, created_by TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE facility_maintenance_log_tasks (
  id INTEGER PRIMARY KEY, log_id INTEGER, task_id INTEGER, created_at TEXT
);
CREATE TABLE torque_calibration_submissions (
  id INTEGER PRIMARY KEY, store_id TEXT, calibration_tech TEXT, units_in_store INTEGER,
  all_pass TEXT, submitted_by TEXT, submitted_at TEXT, ip_address TEXT, gf_entry_id INTEGER
);
CREATE TABLE torque_calibration_wrenches (
  id INTEGER PRIMARY KEY, submission_id INTEGER, wrench_number INTEGER,
  serial_number TEXT, torque_reading TEXT, result TEXT
);
""")

today = datetime.date.today()
def d(days_ago): return (today - datetime.timedelta(days=days_ago)).isoformat() + " 10:00:00"

# Stores 101, 102, 103
cur.executemany("INSERT INTO stores (store_id, company_id, store_name, address, city, state, zip_code, store_phone, store_email, manager_email, manager_name, is_active, date_created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
    (101, 1, "Rusty Wrench - Downtown", "123 Main St", "Austin", "TX", "78701", "512-555-0101", "store101@rusty.com", "mgr101@rusty.com", "Dana Cole", "1", "2020-01-01"),
    (102, 1, "Rusty Wrench - North", "456 Oak Ave", "Austin", "TX", "78753", "512-555-0102", "store102@rusty.com", "mgr102@rusty.com", "Sam Reyes", "1", "2020-01-01"),
    (103, 1, "Rusty Wrench - South", "789 Pine Rd", "Austin", "TX", "78745", "512-555-0103", "store103@rusty.com", "mgr103@rusty.com", "Pat Nguyen", "1", "2020-01-01"),
])

cur.executemany("INSERT INTO rosters (emp_id, first_name, last_name, store_id, status, pay_type, hourly_rate, phone, is_trainer, date_added) VALUES (?,?,?,?,?,?,?,?,?,?)", [
    ("E1", "John", "Smith", 101, 1, "hourly", 22.5, "512-555-1001", 1, "2021-01-01"),
    ("E2", "Maria", "Lopez", 101, 1, "hourly", 20.0, "512-555-1002", 0, "2021-02-01"),
    ("E3", "Alex", "Kim", 102, 1, "hourly", 21.0, "512-555-1003", 0, "2021-03-01"),
])

# Torque calibration: store 101 fails today, store 102 submits OK today, store 103 doesn't submit today
cur.execute("INSERT INTO torque_calibration_submissions (id, store_id, calibration_tech, units_in_store, all_pass, submitted_by, submitted_at) VALUES (1,'101','Tech A',5,'FAIL','Tech A',?)", (d(0),))
cur.execute("INSERT INTO torque_calibration_wrenches (submission_id, wrench_number, serial_number, torque_reading, result) VALUES (1,1,'SN-001','45 ft-lb','FAIL')")
cur.execute("INSERT INTO torque_calibration_wrenches (submission_id, wrench_number, serial_number, torque_reading, result) VALUES (1,2,'SN-002','50 ft-lb','PASS')")
cur.execute("INSERT INTO torque_calibration_submissions (id, store_id, calibration_tech, units_in_store, all_pass, submitted_by, submitted_at) VALUES (2,'102','Tech B',3,'PASS','Tech B',?)", (d(0),))
cur.execute("INSERT INTO torque_calibration_wrenches (submission_id, wrench_number, serial_number, torque_reading, result) VALUES (2,1,'SN-101','48 ft-lb','PASS')")

# Equipment issues this week
cur.execute("INSERT INTO equipment_check_items (id, frequency, equipment, check_name, check_description, display_order, severity_level, is_active) VALUES (1,'daily','Compressor','Pressure check','Check pressure gauge',1,'2',1)")
cur.execute("INSERT INTO equipment_check_items (id, frequency, equipment, check_name, check_description, display_order, severity_level, is_active) VALUES (2,'daily','Lift','Hydraulic check','Check hydraulic fluid',2,'2',1)")
cur.execute("INSERT INTO equipment_maintenance_submissions (id, store_id, frequency, technician, submitted_at) VALUES (1,'101','daily','John Smith',?)", (d(1),))
cur.execute("INSERT INTO equipment_maintenance_checks (submission_id, check_item_id, status, issue_description) VALUES (1,1,'Report Issue','Pressure gauge reading low')")
cur.execute("INSERT INTO equipment_maintenance_submissions (id, store_id, frequency, technician, submitted_at) VALUES (2,'102','daily','Alex Kim',?)", (d(2),))
cur.execute("INSERT INTO equipment_maintenance_checks (submission_id, check_item_id, status, issue_description) VALUES (2,1,'Report Issue','Pressure gauge stuck')")
cur.execute("INSERT INTO equipment_maintenance_checks (submission_id, check_item_id, status) VALUES (2,2,'OK')")

# Facility maintenance log
cur.execute("INSERT INTO facility_maintenance_logs (store_id, date_completed, service_provider, notes) VALUES ('101', ?, 'ACME HVAC', 'Quarterly HVAC service')", (d(10),))

con.commit()
con.close()
print(f"seeded {DB_PATH}")
