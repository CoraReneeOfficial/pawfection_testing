with open("templates/manage_users.html", "r") as f:
    content = f.read()

search = """                                <div x-data="{ confirmingDelete: false }" style="display: inline-block;">
                                    <button x-show="!confirmingDelete" @click="confirmingDelete = true" type="button" class="button button-danger">Delete</button>
                                    <form x-show="confirmingDelete" x-cloak method="POST" action="{{ url_for('management.delete_user', user_id=user_account.id) }}" style="display: flex; align-items: center; gap: 0.5rem; background-color: var(--danger-color); padding: 0.2rem 0.5rem; border-radius: var(--border-radius); color: white;">
                                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                                        <span style="font-size: 0.8rem; font-weight: bold;">Sure?</span>
                                        <button type="submit" class="button" style="background-color: white; color: var(--danger-color); border: none; padding: 0.1rem 0.4rem; font-size: 0.75rem;">Yes</button>
                                        <button @click="confirmingDelete = false" type="button" class="button" style="background-color: transparent; color: white; border: 1px solid white; padding: 0.1rem 0.4rem; font-size: 0.75rem;">No</button>
                                    </form>
                                </div>"""

replace = """                                <div x-data="{ confirmingDelete: false }" style="display: inline-block;">
                                    <button x-show="!confirmingDelete" @click="confirmingDelete = true" type="button" class="button button-danger" aria-label="Delete user {{ user_account.username }}">Delete</button>
                                    <form x-show="confirmingDelete" x-cloak method="POST" action="{{ url_for('management.delete_user', user_id=user_account.id) }}" style="display: flex; align-items: center; gap: 0.5rem; background-color: var(--danger-color); padding: 0.2rem 0.5rem; border-radius: var(--border-radius); color: white;">
                                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                                        <span style="font-size: 0.8rem; font-weight: bold;" aria-hidden="true">Sure?</span>
                                        <button type="submit" class="button" style="background-color: white; color: var(--danger-color); border: none; padding: 0.1rem 0.4rem; font-size: 0.75rem;" aria-label="Confirm delete user {{ user_account.username }}">Yes</button>
                                        <button @click="confirmingDelete = false" type="button" class="button" style="background-color: transparent; color: white; border: 1px solid white; padding: 0.1rem 0.4rem; font-size: 0.75rem;" aria-label="Cancel delete user">No</button>
                                    </form>
                                </div>"""

with open("templates/manage_users.html", "w") as f:
    f.write(content.replace(search, replace))
