# -*- coding: utf-8 -*-

from flask import Blueprint

blueprint = Blueprint(
    'conductor_uploads', __name__, url_prefix='/conductor/upload',
    template_folder='../templates'
)

from . import views
