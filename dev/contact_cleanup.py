# 1) 停用页头"联系我们"CTA 按钮
cta = env.ref('website.header_call_to_action', raise_if_not_found=False)
if cta and cta.active:
    cta.active = False
    print('CTA_DEACTIVATED')

# 2) 删除导航菜单中的"联系我们"
menu = env.ref('website.menu_contactus', raise_if_not_found=False)
if menu:
    menu.unlink()
    print('CONTACTUS_MENU_DELETED')

# 3) 页脚去掉"联系我们"链接（重写页脚 arch，仅保留 学习平台）
FOOTER_ARCH = '''<data inherit_id="website.layout" name="Default" active="True">
    <xpath expr="//div[@id='footer']" position="replace">
        <div id="footer" class="oe_structure oe_structure_solo border text-break" t-ignore="true" t-if="not no_footer" style="--box-border-left-width: 0px; --box-border-right-width: 0px;">
            <section class="s_text_block pt32 pb24" data-snippet="s_text_block" data-name="Container">
                <div class="container">
                    <div class="row align-items-center">
                        <div class="col-lg-8">
                            <h5 class="mb-1">数学辅导中心 · 学习数据平台</h5>
                            <p class="mb-0 text-muted">记录每一次课、每一份作业、每一场考试，让学习进步看得见。</p>
                        </div>
                        <div class="col-lg-4 text-lg-end">
                            <ul class="list-unstyled mb-0">
                                <li><a href="/my/learning">学习平台</a></li>
                            </ul>
                        </div>
                    </div>
                </div>
            </section>
        </div>
    </xpath>
</data>'''
footer = env.ref('website.footer_custom')
footer.with_context(lang='en_US').arch_db = FOOTER_ARCH
footer.with_context(lang='zh_CN').arch_db = FOOTER_ARCH
print('FOOTER_UPDATED')

env.cr.commit()
print('CONTACT_CLEANUP_DONE')
