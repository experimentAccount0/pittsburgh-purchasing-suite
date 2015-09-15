# -*- coding: utf-8 -*-

from flask import current_app
import datetime
from purchasing.database import (
    Column,
    Model,
    db,
    ReferenceCol,
)
from sqlalchemy.schema import Table
from sqlalchemy.orm import backref
from sqlalchemy.dialects.postgres import ARRAY
from sqlalchemy.dialects.postgresql import TSVECTOR

from purchasing.data.models import ContractType

category_vendor_association_table = Table(
    'category_vendor_association', Model.metadata,
    Column('category_id', db.Integer, db.ForeignKey('category.id', ondelete='SET NULL'), index=True),
    Column('vendor_id', db.Integer, db.ForeignKey('vendor.id', ondelete='SET NULL'), index=True)
)

category_opportunity_association_table = Table(
    'category_opportunity_association', Model.metadata,
    Column('category_id', db.Integer, db.ForeignKey('category.id', ondelete='SET NULL'), index=True),
    Column('opportunity_id', db.Integer, db.ForeignKey('opportunity.id', ondelete='SET NULL'), index=True)
)

opportunity_vendor_association_table = Table(
    'opportunity_vendor_association_table', Model.metadata,
    Column('opportunity_id', db.Integer, db.ForeignKey('opportunity.id', ondelete='SET NULL'), index=True),
    Column('vendor_id', db.Integer, db.ForeignKey('vendor.id', ondelete='SET NULL'), index=True)
)

class Category(Model):
    __tablename__ = 'category'

    id = Column(db.Integer, primary_key=True, index=True)
    nigp_codes = Column(ARRAY(db.Integer()))
    category = Column(db.String(255))
    subcategory = Column(db.String(255))
    category_friendly_name = Column(db.Text)
    examples = Column(db.Text)
    examples_tsv = Column(TSVECTOR)

    def __unicode__(self):
        return '{sub} (in {main})'.format(sub=self.category_friendly_name, main=self.category)

    @classmethod
    def parent_category_query_factory(cls):
        '''Return all of the parent categories
        '''
        return db.session.query(db.distinct(cls.category).label('category')).order_by('category')

class Opportunity(Model):
    __tablename__ = 'opportunity'

    id = Column(db.Integer, primary_key=True)
    created_at = Column(db.DateTime, default=datetime.datetime.utcnow())
    department_id = ReferenceCol('department', ondelete='SET NULL', nullable=True)
    department = db.relationship(
        'Department', backref=backref('opportunities', lazy='dynamic')
    )
    contact_id = ReferenceCol('users', ondelete='SET NULL')
    contact = db.relationship(
        'User', backref=backref('opportunities', lazy='dynamic'),
        foreign_keys='Opportunity.contact_id'
    )
    title = Column(db.String(255))
    description = Column(db.Text)
    categories = db.relationship(
        'Category',
        secondary=category_opportunity_association_table,
        backref='opportunities',
        collection_class=set
    )
    # Date opportunity should be made public on beacon
    planned_publish = Column(db.DateTime, nullable=False)
    # Date opportunity accepts responses
    planned_submission_start = Column(db.DateTime, nullable=False)
    # Date opportunity stops accepting responses
    planned_submission_end = Column(db.DateTime, nullable=False)
    # Created from contract
    created_from_id = ReferenceCol('contract', ondelete='cascade', nullable=True)

    # documents needed from the vendors
    vendor_documents_needed = Column(ARRAY(db.Integer()))

    created_by_id = ReferenceCol('users', ondelete='SET NULL')
    created_by = db.relationship(
        'User', backref=backref('opportunities_created', lazy='dynamic'),
        foreign_keys='Opportunity.created_by_id'
    )
    is_public = Column(db.Boolean(), default=False)

    # Date opportunity was actually made public on beacon
    published_at = Column(db.DateTime, nullable=True)
    publish_notification_sent = Column(db.Boolean, default=False, nullable=False)

    opportunity_type_id = ReferenceCol('contract_type', ondelete='SET NULL', nullable=True)
    opportunity_type = db.relationship(
        'ContractType', backref=backref('opportunities', lazy='dynamic'),
    )

    def coerce_to_date(self, field):
        if isinstance(field, datetime.datetime):
            return field.date()
        if isinstance(field, datetime.date):
            return field
        return field

    @property
    def is_published(self):
        return self.coerce_to_date(self.planned_publish) <= datetime.date.today() and self.is_public

    @property
    def is_upcoming(self):
        return self.coerce_to_date(self.planned_publish) <= datetime.date.today() and \
            not self.is_submission_start and not self.is_submission_end and self.is_public

    @property
    def is_submission_start(self):
        return self.coerce_to_date(self.planned_submission_start) <= datetime.date.today() and \
            not self.is_submission_end and self.is_public

    @property
    def is_submission_end(self):
        return self.coerce_to_date(self.planned_submission_end) <= datetime.date.today() and self.is_public

    def can_view(self, user):
        '''Check if a user can see opportunity detail
        '''
        return False if user.is_anonymous() and not self.is_published else True

    def can_edit(self, user):
        '''Check if a user can edit the contract
        '''
        if self.is_public and user.role.name in ('conductor', 'admin', 'superadmin'):
            return True
        elif not self.is_public and \
            (user.role.name in ('conductor', 'admin', 'superadmin') or
                user.id in (self.created_by_id, self.contact_id)):
                return True
        return False

    def estimate_submission_start(self):
        '''Returns the month/year based on planned_submission_start
        '''
        return self.planned_submission_start.strftime('%B %d, %Y')

    def estimate_submission_end(self):
        '''
        '''
        return self.planned_submission_end.strftime('%B %d, %Y')

    def get_needed_documents(self):
        return RequiredBidDocument.query.filter(
            RequiredBidDocument.id.in_(self.documents_needed)
        ).all()

    def get_events(self):
        '''Returns the dates out as a nice ordered list for rendering
        '''
        return [
            {
                'event': 'bid_submission_start', 'classes': 'event event-submission_start',
                'date': self.estimate_submission_start(),
                'description': 'Opportunity opens for submissions.'
            },
            {
                'event': 'bid_submission_end', 'classes': 'event event-submission_end',
                'date': self.estimate_submission_end(),
                'description': 'Deadline to submit proposals.'
            }
        ]

class OpportunityDocument(Model):
    __tablename__ = 'opportunity_document'

    id = Column(db.Integer, primary_key=True, index=True)
    opportunity_id = ReferenceCol('opportunity', ondelete='cascade')
    opportunity = db.relationship(
        'Opportunity',
        backref=backref('opportunity_documents', lazy='dynamic', cascade='all, delete-orphan')
    )

    name = Column(db.String(255))
    href = Column(db.Text())

    def get_href(self):
        '''Returns a proper link to a file
        '''
        if current_app.config['UPLOAD_S3']:
            return self.href
        else:
            if self.href.startswith('http'):
                return self.href
            return 'file://{}'.format(self.href)

    def clean_name(self):
        '''Replaces underscores with spaces
        '''
        return self.name.replace('_', ' ')

class RequiredBidDocument(Model):
    __tablename__ = 'document'

    id = Column(db.Integer, primary_key=True, index=True)
    display_name = Column(db.String(255), nullable=False)
    description = Column(db.Text, nullable=False)
    form_href = Column(db.String(255))

    def get_choices(self):
        return (self.id, [self.display_name, self.description, self.form_href])

class Vendor(Model):
    __tablename__ = 'vendor'

    id = Column(db.Integer, primary_key=True, index=True)
    business_name = Column(db.String(255), nullable=False)
    email = Column(db.String(80), unique=True, nullable=False)
    created_at = Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    first_name = Column(db.String(30), nullable=True)
    last_name = Column(db.String(30), nullable=True)
    phone_number = Column(db.String(20))
    fax_number = Column(db.String(20))
    minority_owned = Column(db.Boolean())
    veteran_owned = Column(db.Boolean())
    woman_owned = Column(db.Boolean())
    disadvantaged_owned = Column(db.Boolean())
    categories = db.relationship(
        'Category',
        secondary=category_vendor_association_table,
        backref='vendors',
        collection_class=set
    )
    opportunities = db.relationship(
        'Opportunity',
        secondary=opportunity_vendor_association_table,
        backref='vendors',
        collection_class=set
    )

    subscribed_to_newsletter = Column(db.Boolean(), default=False)

    @classmethod
    def newsletter_subscribers(cls):
        return cls.query.filter(cls.subscribed_to_newsletter == True).all()

    def __unicode__(self):
        return self.email
