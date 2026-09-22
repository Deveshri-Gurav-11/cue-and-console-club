import os, json, uuid
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session as flask_session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-only-change-me-before-deploying')
db_url = os.getenv('DATABASE_URL', 'sqlite:///gamehub.db')
if db_url.startswith('postgres://'): db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
RESOURCES = ['Pool 1', 'Pool 2', 'Snooker', 'PS4', 'PS5']

class User(db.Model):
    id=db.Column(db.Integer, primary_key=True); username=db.Column(db.String(80), unique=True, nullable=False)
    password_hash=db.Column(db.String(255), nullable=False); role=db.Column(db.String(20), default='staff')
    def set_password(self,p): self.password_hash=generate_password_hash(p)
    def check_password(self,p): return check_password_hash(self.password_hash,p)
class Setting(db.Model):
    key=db.Column(db.String(100), primary_key=True); value=db.Column(db.Text, nullable=False)
class Product(db.Model):
    id=db.Column(db.Integer,primary_key=True); name=db.Column(db.String(120),nullable=False); category=db.Column(db.String(60),default='Snacks')
    price=db.Column(db.Numeric(10,2),nullable=False,default=0); active=db.Column(db.Boolean,default=True); stock=db.Column(db.Integer,nullable=True)
class GameSession(db.Model):
    id=db.Column(db.Integer,primary_key=True); code=db.Column(db.String(24),unique=True,nullable=False)
    resource=db.Column(db.String(30),nullable=False,index=True); customer=db.Column(db.String(120),default='Walk-in')
    started_at=db.Column(db.DateTime,nullable=False); ended_at=db.Column(db.DateTime); planned_minutes=db.Column(db.Integer)
    estimated_end=db.Column(db.DateTime); status=db.Column(db.String(20),default='active',index=True); controllers=db.Column(db.Integer,default=0)
    paused_seconds=db.Column(db.Integer,default=0); pause_started=db.Column(db.DateTime); rate_snapshot=db.Column(db.Text,default='{}')
    billable_minutes=db.Column(db.Integer,default=0); gaming_total=db.Column(db.Numeric(10,2),default=0); bill_id=db.Column(db.Integer); booking_id=db.Column(db.Integer,nullable=True)
class Booking(db.Model):
    id=db.Column(db.Integer,primary_key=True); code=db.Column(db.String(24),unique=True,nullable=False)
    resource=db.Column(db.String(30),nullable=False,index=True); customer=db.Column(db.String(120),nullable=False); phone=db.Column(db.String(40),default='')
    starts_at=db.Column(db.DateTime,nullable=False,index=True); ends_at=db.Column(db.DateTime,nullable=False,index=True)
    controllers=db.Column(db.Integer,default=0); advance=db.Column(db.Numeric(10,2),default=0); status=db.Column(db.String(20),default='confirmed',index=True); notes=db.Column(db.Text,default='')
    created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Bill(db.Model):
    id=db.Column(db.Integer,primary_key=True); code=db.Column(db.String(24),unique=True,nullable=False); session_id=db.Column(db.Integer,nullable=True)
    resource=db.Column(db.String(30),default='Product sale'); customer=db.Column(db.String(120),default='Walk-in')
    started_at=db.Column(db.DateTime); ended_at=db.Column(db.DateTime); duration_minutes=db.Column(db.Integer,default=0)
    gaming_total=db.Column(db.Numeric(10,2),default=0); products_json=db.Column(db.Text,default='[]'); product_total=db.Column(db.Numeric(10,2),default=0)
    discount=db.Column(db.Numeric(10,2),default=0); total=db.Column(db.Numeric(10,2),default=0); paid=db.Column(db.Numeric(10,2),default=0)
    payment_status=db.Column(db.String(20),default='unpaid'); created_at=db.Column(db.DateTime,default=datetime.utcnow,index=True)
class Payment(db.Model):
    id=db.Column(db.Integer,primary_key=True); bill_id=db.Column(db.Integer,nullable=False,index=True); method=db.Column(db.String(20)); amount=db.Column(db.Numeric(10,2)); created_at=db.Column(db.DateTime,default=datetime.utcnow)
class Audit(db.Model):
    id=db.Column(db.Integer,primary_key=True); username=db.Column(db.String(80)); action=db.Column(db.String(120)); details=db.Column(db.Text); created_at=db.Column(db.DateTime,default=datetime.utcnow)

def now(): return datetime.utcnow()
def local(dt): return dt.strftime('%Y-%m-%d %H:%M') if dt else ''
def money(v): return float(Decimal(str(v or 0)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
def pricing():
    defaults={r:{'rate_per_hour':300 if r.startswith('Pool') else 250 if r=='Snooker' else 200,'controller_per_hour':0,'billing_increment':1,'minimum_minutes':0,'minimum_charge':0} for r in RESOURCES}
    s=Setting.query.filter_by(key='pricing').first()
    if s:
        try: defaults.update(json.loads(s.value))
        except Exception: pass
    return defaults
def audit(action,details=''):
    db.session.add(Audit(username=flask_session.get('username','system'),action=action,details=details))
def api_login(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        if not flask_session.get('user_id'): return jsonify(error='Please log in again.'),401
        return fn(*a,**kw)
    return wrapped
def owner_only(): return flask_session.get('role')=='owner'
def to_dt(value):
    if not value: return None
    try: return datetime.fromisoformat(value.replace('Z',''))
    except ValueError: return None
def overlap(resource,start,end,exclude_id=None):
    q=Booking.query.filter(Booking.resource==resource,Booking.status=='confirmed',Booking.starts_at<end,Booking.ends_at>start)
    if exclude_id: q=q.filter(Booking.id!=exclude_id)
    if q.first(): return True
    active=GameSession.query.filter_by(resource=resource,status='active').first()
    if active:
        # Block booking across an active session when its estimated end is unknown or overlaps.
        active_end=active.estimated_end or (active.started_at+timedelta(minutes=active.planned_minutes) if active.planned_minutes else None)
        if not active_end or (active.started_at<end and active_end>start): return True
    return False
def active_duration(s):
    end=s.ended_at or now(); elapsed=max(0,int((end-s.started_at).total_seconds())-s.paused_seconds)
    if s.pause_started and not s.ended_at: elapsed-=max(0,int((now()-s.pause_started).total_seconds()))
    return max(0,elapsed)
def session_charge(s):
    p=pricing().get(s.resource,{})
    snap=json.loads(s.rate_snapshot or '{}')
    rate=Decimal(str(snap.get('rate_per_hour',p.get('rate_per_hour',0))))
    cr=Decimal(str(snap.get('controller_per_hour',p.get('controller_per_hour',0))))
    mins=active_duration(s)/60
    inc=max(1,int(snap.get('billing_increment',p.get('billing_increment',1))))
    bill_mins=int((Decimal(str(mins))/Decimal(inc)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))*inc
    bill_mins=max(bill_mins,int(snap.get('minimum_minutes',p.get('minimum_minutes',0))))
    total=(rate+cr*int(s.controllers or 0))*Decimal(bill_mins)/Decimal(60)
    total=max(total,Decimal(str(snap.get('minimum_charge',p.get('minimum_charge',0)))))
    return bill_mins,money(total)
def serialize_session(s):
    mins,charge=session_charge(s) if s.status in ('active','paused') else (s.billable_minutes,money(s.gaming_total))
    return {'id':s.id,'code':s.code,'resource':s.resource,'customer':s.customer,'started_at':local(s.started_at),'ended_at':local(s.ended_at),'status':s.status,'controllers':s.controllers,'duration_minutes':mins,'elapsed_seconds':active_duration(s),'estimated_end':local(s.estimated_end),'estimated_charge':charge}
def serialize_booking(b): return {'id':b.id,'code':b.code,'resource':b.resource,'customer':b.customer,'phone':b.phone,'starts_at':local(b.starts_at),'ends_at':local(b.ends_at),'controllers':b.controllers,'advance':money(b.advance),'status':b.status,'notes':b.notes}

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=User.query.filter_by(username=request.form.get('username','').strip()).first()
        if u and u.check_password(request.form.get('password','')):
            flask_session.clear(); flask_session.update(user_id=u.id,username=u.username,role=u.role)
            return redirect(url_for('home'))
        flash('Invalid username or password.','error')
    return render_template('login.html')
@app.get('/logout')
def logout(): flask_session.clear(); return redirect(url_for('login'))
@app.get('/')
def home():
    if not flask_session.get('user_id'): return redirect(url_for('login'))
    return render_template('index.html',username=flask_session['username'],role=flask_session['role'])
@app.get('/manifest.json')
def manifest(): return jsonify(name='Cue & Console Club',short_name='Cue & Console',start_url='/',display='standalone',background_color='#0b1020',theme_color='#0b1020',icons=[{'src':'/static/icon.svg','sizes':'any','type':'image/svg+xml'}])
@app.get('/sw.js')
def sw():
    from flask import Response
    return Response("self.addEventListener('install',e=>self.skipWaiting());self.addEventListener('activate',e=>self.clients.claim());self.addEventListener('fetch',e=>{});",mimetype='application/javascript')


@app.post('/api/change-password')
@api_login
def change_password():
    d=request.get_json(force=True)
    current=d.get('current_password','')
    new=d.get('new_password','')
    confirm=d.get('confirm_password','')
    user=User.query.get(flask_session.get('user_id'))
    if not user or not user.check_password(current):
        return jsonify(error='Current password is incorrect.'), 400
    if len(new)<8:
        return jsonify(error='New password must be at least 8 characters.'), 400
    if new != confirm:
        return jsonify(error='New passwords do not match.'), 400
    user.set_password(new)
    audit('password_changed', user.username)
    db.session.commit()
    return jsonify(ok=True)

@app.get('/api/bootstrap')
@api_login
def bootstrap():
    active=GameSession.query.filter(GameSession.status.in_(['active','paused'])).all()
    upcoming=Booking.query.filter(Booking.status=='confirmed',Booking.starts_at>=now()).order_by(Booking.starts_at).limit(40).all()
    products=Product.query.filter_by(active=True).order_by(Product.category,Product.name).all()
    today=date.today(); bills=Bill.query.filter(db.func.date(Bill.created_at)==today).all()
    return jsonify(resources=RESOURCES,sessions=[serialize_session(s) for s in active],bookings=[serialize_booking(b) for b in upcoming],products=[{'id':p.id,'name':p.name,'category':p.category,'price':money(p.price),'stock':p.stock} for p in products],pricing=pricing(),role=flask_session['role'],today={'revenue':sum(money(b.paid) for b in bills),'sessions':GameSession.query.filter(db.func.date(GameSession.started_at)==today).count(),'pending':sum(max(0,money(b.total)-money(b.paid)) for b in bills)})

@app.post('/api/sessions')
@api_login
def start_session():
    d=request.get_json(force=True); r=d.get('resource')
    if r not in RESOURCES: return jsonify(error='Choose a valid resource.'),400
    if GameSession.query.filter(GameSession.resource==r,GameSession.status.in_(['active','paused'])).first(): return jsonify(error='This resource already has an active session.'),409
    st=now(); planned=int(d.get('planned_minutes') or 0); est=st+timedelta(minutes=planned) if planned>0 else to_dt(d.get('estimated_end'))
    # Do not start a walk-in if it conflicts with an upcoming confirmed reservation.
    nextq=Booking.query.filter_by(resource=r,status='confirmed').filter(Booking.starts_at>st)
    if d.get('booking_id'): nextq=nextq.filter(Booking.id!=d.get('booking_id'))
    nextb=nextq.order_by(Booking.starts_at).first()
    if nextb and (not est or est>nextb.starts_at): return jsonify(error=f"This resource has a booking at {local(nextb.starts_at)}. Set a duration that ends before it."),409
    p=pricing().get(r,{})
    s=GameSession(code='S-'+uuid.uuid4().hex[:8].upper(),resource=r,customer=(d.get('customer') or 'Walk-in').strip(),started_at=st,planned_minutes=planned or None,estimated_end=est,controllers=max(0,int(d.get('controllers') or 0)),rate_snapshot=json.dumps(p),booking_id=d.get('booking_id'))
    if d.get('booking_id'):
        bk=Booking.query.get(d.get('booking_id'))
        if not bk or bk.status!='confirmed' or bk.resource!=r: return jsonify(error='Booking is no longer available for check-in.'),409
        bk.status='playing'
    db.session.add(s); audit('session_started',s.code); db.session.commit(); return jsonify(session=serialize_session(s))
@app.patch('/api/sessions/<int:sid>')
@api_login
def update_session(sid):
    s=GameSession.query.get_or_404(sid); d=request.get_json(force=True); action=d.get('action')
    if s.status not in ('active','paused'): return jsonify(error='Session is already closed.'),400
    if action=='pause' and s.status=='active': s.status='paused'; s.pause_started=now()
    elif action=='resume' and s.status=='paused':
        if s.pause_started: s.paused_seconds += int((now()-s.pause_started).total_seconds())
        s.pause_started=None; s.status='active'
    elif action=='extend':
        mins=int(d.get('minutes') or 0)
        if mins<=0: return jsonify(error='Enter extension minutes.'),400
        s.estimated_end=(s.estimated_end or now())+timedelta(minutes=mins); s.planned_minutes=(s.planned_minutes or 0)+mins
    elif action=='estimate':
        s.estimated_end=to_dt(d.get('estimated_end')); s.planned_minutes=max(0,int(d.get('planned_minutes') or 0)) or None
    elif action=='controllers': s.controllers=max(0,int(d.get('controllers') or 0))
    else: return jsonify(error='Unsupported session action.'),400
    audit('session_'+action,s.code); db.session.commit(); return jsonify(session=serialize_session(s))

@app.post('/api/bookings')
@api_login
def create_booking():
    d=request.get_json(force=True); r=d.get('resource'); start=to_dt(d.get('starts_at')); end=to_dt(d.get('ends_at'))
    if r not in RESOURCES or not start or not end or end<=start or not d.get('customer','').strip(): return jsonify(error='Enter resource, customer, valid start and end times.'),400
    if start<now()-timedelta(minutes=1): return jsonify(error='Booking must be in the future.'),400
    if overlap(r,start,end): return jsonify(error='That slot overlaps an existing booking or active session.'),409
    b=Booking(code='B-'+uuid.uuid4().hex[:8].upper(),resource=r,customer=d['customer'].strip(),phone=d.get('phone',''),starts_at=start,ends_at=end,controllers=max(0,int(d.get('controllers') or 0)),advance=money(d.get('advance') or 0),notes=d.get('notes',''))
    db.session.add(b); audit('booking_created',b.code); db.session.commit(); return jsonify(booking=serialize_booking(b))
@app.patch('/api/bookings/<int:bid>')
@api_login
def edit_booking(bid):
    b=Booking.query.get_or_404(bid); d=request.get_json(force=True)
    if b.status!='confirmed': return jsonify(error='Only confirmed bookings can be edited.'),400
    r=d.get('resource',b.resource); start=to_dt(d.get('starts_at')) or b.starts_at; end=to_dt(d.get('ends_at')) or b.ends_at
    if r not in RESOURCES or end<=start: return jsonify(error='Invalid resource or time range.'),400
    if overlap(r,start,end,b.id): return jsonify(error='That slot overlaps another booking or active session.'),409
    b.resource=r; b.starts_at=start; b.ends_at=end; b.customer=d.get('customer',b.customer).strip(); b.phone=d.get('phone',b.phone); b.controllers=max(0,int(d.get('controllers',b.controllers) or 0)); b.advance=money(d.get('advance',b.advance) or 0); b.notes=d.get('notes',b.notes)
    audit('booking_edited',b.code); db.session.commit(); return jsonify(booking=serialize_booking(b))
@app.delete('/api/bookings/<int:bid>')
@api_login
def delete_booking(bid):
    b=Booking.query.get_or_404(bid)
    if not owner_only() and b.status!='confirmed': return jsonify(error='Only owner can remove non-confirmed bookings.'),403
    b.status='cancelled'; audit('booking_cancelled',b.code); db.session.commit(); return jsonify(ok=True)

@app.post('/api/products')
@api_login
def add_product():
    if not owner_only(): return jsonify(error='Owner permission required.'),403
    d=request.get_json(force=True); name=d.get('name','').strip()
    if not name: return jsonify(error='Product name is required.'),400
    p=Product(name=name,category=d.get('category','Snacks'),price=money(d.get('price') or 0),stock=int(d['stock']) if str(d.get('stock','')).isdigit() else None)
    db.session.add(p); audit('product_added',name); db.session.commit(); return jsonify(id=p.id)
@app.patch('/api/products/<int:pid>')
@api_login
def update_product(pid):
    if not owner_only(): return jsonify(error='Owner permission required.'),403
    p=Product.query.get_or_404(pid); d=request.get_json(force=True)
    for k in ('name','category'):
        if k in d: setattr(p,k,d[k].strip())
    if 'price' in d: p.price=money(d['price'])
    if 'active' in d: p.active=bool(d['active'])
    if 'stock' in d: p.stock=int(d['stock']) if str(d['stock']).isdigit() else None
    audit('product_updated',p.name); db.session.commit(); return jsonify(ok=True)
@app.put('/api/pricing')
@api_login
def save_pricing():
    if not owner_only(): return jsonify(error='Owner permission required.'),403
    d=request.get_json(force=True); current=pricing()
    for r in RESOURCES:
        if r in d:
            try:
                x=d[r]; current[r]={'rate_per_hour':max(0,float(x.get('rate_per_hour',0))),'controller_per_hour':max(0,float(x.get('controller_per_hour',0))),'billing_increment':max(1,int(x.get('billing_increment',1))),'minimum_minutes':max(0,int(x.get('minimum_minutes',0))),'minimum_charge':max(0,float(x.get('minimum_charge',0)))}
            except (ValueError,TypeError): return jsonify(error=f'Invalid pricing for {r}.'),400
    row=Setting.query.filter_by(key='pricing').first()
    if not row: row=Setting(key='pricing',value='{}'); db.session.add(row)
    row.value=json.dumps(current); audit('pricing_updated','Rates changed'); db.session.commit(); return jsonify(ok=True,pricing=current)

@app.post('/api/checkout')
@api_login
def checkout():
    d=request.get_json(force=True); sid=d.get('session_id'); s=GameSession.query.get(sid) if sid else None
    if sid and (not s or s.status not in ('active','paused')): return jsonify(error='Session is not billable.'),400
    items=[]; ptotal=Decimal('0.00')
    for line in d.get('items',[]):
        p=Product.query.get(line.get('product_id')); qty=max(0,int(line.get('quantity') or 0))
        if p and p.active and qty:
            price=Decimal(str(p.price)); sub=price*qty; ptotal+=sub; items.append({'product_id':p.id,'name':p.name,'quantity':qty,'unit_price':money(price),'subtotal':money(sub)})
    gaming=Decimal('0.00'); dur=0; started=ended=None; resource='Product sale'; customer=d.get('customer','Walk-in')
    if s:
        if s.pause_started:
            s.paused_seconds+=int((now()-s.pause_started).total_seconds()); s.pause_started=None
        s.ended_at=now(); dur,g= session_charge(s); gaming=Decimal(str(g)); s.status='completed'; s.billable_minutes=dur; s.gaming_total=g
        started=s.started_at; ended=s.ended_at; resource=s.resource; customer=s.customer
    discount=Decimal(str(max(0,float(d.get('discount') or 0)))); total=max(Decimal('0'),gaming+ptotal-discount)
    paid=Decimal(str(max(0,float(d.get('paid') or 0)))); paid=min(paid,total)
    method=d.get('method','Cash')
    if method not in ('Cash','UPI','Split','Unpaid'): method='Cash'
    b=Bill(code='G-'+uuid.uuid4().hex[:8].upper(),session_id=s.id if s else None,resource=resource,customer=customer,started_at=started,ended_at=ended,duration_minutes=dur,gaming_total=gaming,products_json=json.dumps(items),product_total=ptotal,discount=discount,total=total,paid=paid,payment_status='paid' if paid>=total else 'partial' if paid>0 else 'unpaid')
    db.session.add(b); db.session.flush()
    if paid>0: db.session.add(Payment(bill_id=b.id,method=method,amount=paid))
    if s: s.bill_id=b.id
    audit('checkout_completed',b.code); db.session.commit()
    return jsonify(bill={'id':b.id,'code':b.code,'total':money(total),'paid':money(paid),'due':money(total-paid),'payment_status':b.payment_status})
@app.get('/api/history')
@api_login
def history():
    day=request.args.get('date'); start=request.args.get('start'); end=request.args.get('end'); resource=request.args.get('resource')
    q=Bill.query
    if day:
        try: dt=date.fromisoformat(day); q=q.filter(db.func.date(Bill.created_at)==dt)
        except ValueError: pass
    if start:
        st=to_dt(start); q=q.filter(Bill.created_at>=st) if st else q
    if end:
        en=to_dt(end); q=q.filter(Bill.created_at<=en) if en else q
    if resource and resource!='All': q=q.filter(Bill.resource==resource)
    bills=q.order_by(Bill.created_at.desc()).limit(500).all()
    result=[]
    for b in bills:
        result.append({'id':b.id,'code':b.code,'resource':b.resource,'customer':b.customer,'started_at':local(b.started_at),'ended_at':local(b.ended_at),'created_at':local(b.created_at),'duration_minutes':b.duration_minutes,'gaming_total':money(b.gaming_total),'products':json.loads(b.products_json or '[]'),'product_total':money(b.product_total),'discount':money(b.discount),'total':money(b.total),'paid':money(b.paid),'due':money(Decimal(str(b.total))-Decimal(str(b.paid))),'payment_status':b.payment_status,'payments':[{'method':p.method,'amount':money(p.amount)} for p in Payment.query.filter_by(bill_id=b.id).all()]})
    return jsonify(bills=result)
@app.get('/api/bookings/all')
@api_login
def all_bookings():
    q=Booking.query
    if request.args.get('date'):
        try: q=q.filter(db.func.date(Booking.starts_at)==date.fromisoformat(request.args['date']))
        except ValueError: pass
    return jsonify(bookings=[serialize_booking(b) for b in q.order_by(Booking.starts_at).limit(500).all()])
@app.get('/api/reports')
@api_login
def reports():
    day=request.args.get('date')
    try: selected=date.fromisoformat(day) if day else date.today()
    except ValueError: selected=date.today()
    sessions=GameSession.query.filter(db.func.date(GameSession.started_at)==selected,GameSession.status=='completed').all()
    bills=Bill.query.filter(db.func.date(Bill.created_at)==selected).all()
    summary={r:{'count':0,'minutes':0,'revenue':0,'slots':[]} for r in RESOURCES}
    for s in sessions:
        x=summary[s.resource]; x['count']+=1; x['minutes']+=s.billable_minutes; x['revenue']+=money(s.gaming_total); x['slots'].append({'customer':s.customer,'start':local(s.started_at),'end':local(s.ended_at),'minutes':s.billable_minutes,'charge':money(s.gaming_total)})
    return jsonify(date=selected.isoformat(),resources=summary,product_revenue=sum(money(b.product_total) for b in bills),total_revenue=sum(money(b.paid) for b in bills),cash=sum(money(p.amount) for b in bills for p in Payment.query.filter_by(bill_id=b.id,method='Cash').all()),upi=sum(money(p.amount) for b in bills for p in Payment.query.filter_by(bill_id=b.id,method='UPI').all()),outstanding=sum(max(0,money(b.total)-money(b.paid)) for b in bills))
@app.post('/api/payments/<int:bill_id>')
@api_login
def add_payment(bill_id):
    b=Bill.query.get_or_404(bill_id); d=request.get_json(force=True); amount=money(d.get('amount') or 0); method=d.get('method','Cash')
    due=max(0,money(Decimal(str(b.total))-Decimal(str(b.paid))))
    if amount<=0 or amount>due or method not in ('Cash','UPI'): return jsonify(error='Enter a valid payment amount and method.'),400
    db.session.add(Payment(bill_id=b.id,method=method,amount=amount)); b.paid=Decimal(str(b.paid))+Decimal(str(amount)); b.payment_status='paid' if b.paid>=b.total else 'partial'; db.session.commit(); return jsonify(ok=True,due=max(0,money(Decimal(str(b.total))-Decimal(str(b.paid)))))

with app.app_context():
    db.create_all()
    if not User.query.first():
        owner=User(username=os.getenv('OWNER_USERNAME','owner'),role='owner'); owner.set_password(os.getenv('OWNER_PASSWORD','ChangeMe123!')); db.session.add(owner)
        staff=User(username=os.getenv('STAFF_USERNAME','staff'),role='staff'); staff.set_password(os.getenv('STAFF_PASSWORD','StaffChange123!')); db.session.add(staff)
    if not Setting.query.filter_by(key='pricing').first(): db.session.add(Setting(key='pricing',value=json.dumps(pricing())))
    db.session.commit()

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT',5000)),debug=False)
