{
    "name": "STYD Odoo Bridge",
    "version": "17.0.0.1.0",
    "summary": "Trusted Odoo security bridge for Speak to your Database",
    "category": "Tools",
    "author": "Speak to your Database",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": True,
}