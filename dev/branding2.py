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
                                <li><a href="/contactus">联系我们</a></li>
                            </ul>
                        </div>
                    </div>
                </div>
            </section>
        </div>
    </xpath>
</data>'''

COPYRIGHT_ARCH = '''<data inherit_id="website.layout" priority="15">
    <xpath expr="//footer//span[hasclass('o_footer_copyright_name')]" position="replace">
        <span class="o_footer_copyright_name me-2 small">Copyright &amp;copy; <t t-out="res_company.name"/></span>
    </xpath>
    <xpath expr="//div[hasclass('o_footer_copyright')]//div[hasclass('col-sm')]" position="attributes">
        <attribute name="class" remove="col-sm text-sm-start" add="col-md d-flex flex-column-reverse gap-2 text-md-start" separator=" "/>
    </xpath>
</data>'''

footer = env.ref('website.footer_custom')
footer.with_context(lang='en_US').arch_db = FOOTER_ARCH
footer.with_context(lang='zh_CN').arch_db = FOOTER_ARCH
print('FOOTER_UPDATED')

cv = env.ref('website.footer_copyright_company_name')
cv.with_context(lang='en_US').arch_db = COPYRIGHT_ARCH
cv.with_context(lang='zh_CN').arch_db = COPYRIGHT_ARCH
print('COPYRIGHT_UPDATED')

env.cr.commit()
print('COMMITTED')
