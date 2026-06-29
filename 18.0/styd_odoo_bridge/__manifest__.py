{
    "name": "Speak To Your Database — Secure Odoo AI Connector",
    "version": "18.0.0.7.0",
    "summary": "Secure read-only connector for Speak To Your Database.",
    "category": "Tools",
    "author": "Speak To Your Database",
    "website": "https://speaktoyourdatabase.com",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": True,
}
