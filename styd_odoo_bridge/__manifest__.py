{
    "name": "STYD Odoo Bridge",
    "version": "16.0.0.1.0",
    "summary": "Trusted Odoo security bridge for Speak to your Database",
    "category": "Tools",
    "author": "Speak to your Database",
    "license": "LGPL-3",
    "depends": ["base", "base_setup"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": True,
}