import re

with open('management/routes.py', 'r') as f:
    content = f.read()

# Add User context
target_add1 = """    log_activity("Viewed Add User page")
    return render_template('user_form.html', mode='add', user_data={'is_groomer': True}) """

replacement_add1 = """    log_activity("Viewed Add User page")
    admins = User.query.filter_by(store_id=session.get('store_id'), is_admin=True).all()
    return render_template('user_form.html', mode='add', user_data={'is_groomer': True}, admins=admins) """

content = content.replace(target_add1, replacement_add1)

target_add2 = """        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict()
            form_data['is_admin'] = is_admin
            form_data['is_groomer'] = is_groomer
            return render_template('user_form.html', mode='add', user_data=form_data), 400"""

replacement_add2 = """        if errors:
            for _, msg in errors.items(): flash(msg, "danger")
            form_data = request.form.to_dict()
            form_data['is_admin'] = is_admin
            form_data['is_groomer'] = is_groomer
            admins = User.query.filter_by(store_id=session.get('store_id'), is_admin=True).all()
            return render_template('user_form.html', mode='add', user_data=form_data, admins=admins), 400"""
content = content.replace(target_add2, replacement_add2)


# Edit user context
target_edit1 = """    log_activity("Viewed Edit User page", details=f"User ID: {user_id}")
    return render_template('user_form.html', mode='edit', user_data=user_to_edit) """

replacement_edit1 = """    log_activity("Viewed Edit User page", details=f"User ID: {user_id}")
    admins = User.query.filter_by(store_id=session.get('store_id'), is_admin=True).all()
    return render_template('user_form.html', mode='edit', user_data=user_to_edit, admins=admins) """
content = content.replace(target_edit1, replacement_edit1)

with open('management/routes.py', 'w') as f:
    f.write(content)
