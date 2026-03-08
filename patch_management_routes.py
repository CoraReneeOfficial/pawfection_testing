import re

with open('management/routes.py', 'r') as f:
    content = f.read()

# 1. Update financials calculation logic
calc_target = """        # Calculate groomer commission vs store cut
        if groomer:
            commission_pct = Decimal(str(groomer.commission_percentage)) if groomer.commission_percentage is not None else Decimal('100.0')
            groomer_cut = amount * (commission_pct / Decimal('100.0'))
            store_cut = amount - groomer_cut

            # Aggregate per groomer
            if groomer.id not in aggregate_data['groomers']:
                aggregate_data['groomers'][groomer.id] = {
                    'name': groomer.username,
                    'total_revenue_generated': Decimal('0.0'),
                    'total_groomer_earnings': Decimal('0.0'),
                    'total_store_cut': Decimal('0.0'),
                    'appointment_count': 0,
                    'commission_pct': float(commission_pct),
                    'employment_type': groomer.employment_type or 'Unknown'
                }

            g_data = aggregate_data['groomers'][groomer.id]
            g_data['total_revenue_generated'] += amount
            g_data['total_groomer_earnings'] += groomer_cut
            g_data['total_store_cut'] += store_cut
            g_data['appointment_count'] += 1

            aggregate_data['overall']['total_store_revenue'] += store_cut
            aggregate_data['overall']['total_groomer_payouts'] += groomer_cut
        else:
            # If no groomer assigned, all goes to store
            aggregate_data['overall']['total_store_revenue'] += amount"""

calc_replacement = """        # Calculate groomer commission vs store cut
        if groomer:
            c_type = groomer.commission_type or 'percentage'
            c_amount = Decimal(str(groomer.commission_amount)) if groomer.commission_amount is not None else Decimal('100.0')

            if c_type == 'percentage':
                groomer_cut = amount * (c_amount / Decimal('100.0'))
            else:
                # Dollar amount
                groomer_cut = min(amount, c_amount)

            store_cut = amount - groomer_cut

            # Aggregate per groomer
            if groomer.id not in aggregate_data['groomers']:
                aggregate_data['groomers'][groomer.id] = {
                    'name': groomer.username,
                    'total_revenue_generated': Decimal('0.0'),
                    'total_groomer_earnings': Decimal('0.0'),
                    'total_store_cut': Decimal('0.0'),
                    'appointment_count': 0,
                    'commission_type': c_type,
                    'commission_amount': float(c_amount),
                    'commission_recipient_id': groomer.commission_recipient_id,
                    'employment_type': groomer.employment_type or 'Unknown'
                }

            g_data = aggregate_data['groomers'][groomer.id]
            g_data['total_revenue_generated'] += amount
            g_data['total_groomer_earnings'] += groomer_cut
            g_data['total_store_cut'] += store_cut
            g_data['appointment_count'] += 1

            aggregate_data['overall']['total_store_revenue'] += store_cut
            aggregate_data['overall']['total_groomer_payouts'] += groomer_cut
        else:
            # If no groomer assigned, all goes to store
            aggregate_data['overall']['total_store_revenue'] += amount"""

content = content.replace(calc_target, calc_replacement)

# 2. Add users logic:
add_user_target = """        try:
            is_admin = bool(request.form.get('is_admin'))
            is_groomer = bool(request.form.get('is_groomer'))

            commission_percentage = 100.0
            if is_groomer:
                commission_percentage = float(request.form.get('commission_percentage', 100.0))
            else:
                commission_percentage = 100.0

            # Pass empty string for security question since we aren't collecting it here
            security_question = ""
            new_user = User(username=username, is_admin=is_admin, is_groomer=is_groomer, store_id=store_id, security_question=security_question, email=email, commission_percentage=commission_percentage)  # Assign store_id, email, commission"""

add_user_replacement = """        try:
            is_admin = bool(request.form.get('is_admin'))
            is_groomer = bool(request.form.get('is_groomer'))

            commission_type = "percentage"
            commission_amount = 100.0
            commission_recipient_id = None

            if is_groomer:
                commission_type = request.form.get('commission_type', 'percentage')
                commission_amount = float(request.form.get('commission_amount', 100.0))
                recipient_val = request.form.get('commission_recipient_id')
                if recipient_val and recipient_val.isdigit():
                    commission_recipient_id = int(recipient_val)

            # Pass empty string for security question since we aren't collecting it here
            security_question = ""
            new_user = User(username=username, is_admin=is_admin, is_groomer=is_groomer, store_id=store_id, security_question=security_question, email=email, commission_type=commission_type, commission_amount=commission_amount, commission_recipient_id=commission_recipient_id)  # Assign store_id, email, commission"""

content = content.replace(add_user_target, add_user_replacement)

# 3. Edit users logic:
edit_user_target = """        try:
            is_admin = bool(request.form.get('is_admin'))
            is_groomer = bool(request.form.get('is_groomer'))

            commission_percentage = user_to_edit.commission_percentage
            if is_groomer:
                commission_percentage = float(request.form.get('commission_percentage', user_to_edit.commission_percentage))

            user_to_edit.username = request.form.get('username')
            user_to_edit.email = email
            user_to_edit.is_admin = is_admin
            user_to_edit.is_groomer = is_groomer
            user_to_edit.commission_percentage = commission_percentage

            # --- Phase 2: Employee Settings ---"""

edit_user_replacement = """        try:
            is_admin = bool(request.form.get('is_admin'))
            is_groomer = bool(request.form.get('is_groomer'))

            if is_groomer:
                user_to_edit.commission_type = request.form.get('commission_type', 'percentage')
                user_to_edit.commission_amount = float(request.form.get('commission_amount', 100.0))
                recipient_val = request.form.get('commission_recipient_id')
                if recipient_val and recipient_val.isdigit():
                    user_to_edit.commission_recipient_id = int(recipient_val)
                else:
                    user_to_edit.commission_recipient_id = None

            user_to_edit.username = request.form.get('username')
            user_to_edit.email = email
            user_to_edit.is_admin = is_admin
            user_to_edit.is_groomer = is_groomer

            # --- Phase 2: Employee Settings ---"""

content = content.replace(edit_user_target, edit_user_replacement)

# Provide admins context to user forms
admin_render_target = """    return render_template('user_form.html', form_action=url_for('management.add_user'), title='Add User', mode='add', user_data=None)"""
admin_render_replacement = """    admins = User.query.filter_by(store_id=session.get('store_id'), is_admin=True).all()
    return render_template('user_form.html', form_action=url_for('management.add_user'), title='Add User', mode='add', user_data=None, admins=admins)"""
content = content.replace(admin_render_target, admin_render_replacement)

admin_render_edit_target = """    return render_template('user_form.html', form_action=url_for('management.edit_user', user_id=user_id), title='Edit User', mode='edit', user_data=user_to_edit)"""
admin_render_edit_replacement = """    admins = User.query.filter_by(store_id=session.get('store_id'), is_admin=True).all()
    return render_template('user_form.html', form_action=url_for('management.edit_user', user_id=user_id), title='Edit User', mode='edit', user_data=user_to_edit, admins=admins)"""
content = content.replace(admin_render_edit_target, admin_render_edit_replacement)


with open('management/routes.py', 'w') as f:
    f.write(content)
